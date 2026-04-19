from __future__ import annotations

import typing as T

import pytest

from op.config import Config, ConnectionConfig, DefaultsConfig, RemoteConfig
from op.models import WorkPackage
from op.tui.app import OpApp
from op.tui.main_screen import MainScreen
from op.tui.update_modal import UpdateModal


def _wp(id: int, subject: str = 'S', lock_version: int = 1) -> WorkPackage:
    return WorkPackage(
        id=id,
        subject=subject,
        type_id=1,
        type_name='Task',
        status_id=1,
        status_name='Neu',
        project_id=10,
        project_name='Web',
        lock_version=lock_version,
    )


def _config(
    *,
    statuses: dict[int, str] | None = None,
    priorities: dict[int, str] | None = None,
) -> Config:
    remote = RemoteConfig(
        statuses=statuses or {1: 'Neu', 2: 'In Bearbeitung', 3: 'Erledigt'},
        types={1: 'Task', 2: 'Bug'},
        priorities=priorities or {8: 'Normal', 9: 'Hoch'},
        users={5: 'Max', 6: 'Anna'},
    )
    return Config(
        connection=ConnectionConfig(base_url='https://op.example.com'),
        defaults=DefaultsConfig(),
        remote=remote,
    )


class FakeClient:
    """Stand-in for OpenProjectClient that records update calls."""

    def __init__(self) -> None:
        self.updates: list[tuple[int, int, dict]] = []

    async def update_work_package(
        self, wp_id: int, *, lock_version: int, changes: dict
    ) -> WorkPackage:
        self.updates.append((wp_id, lock_version, changes))
        return _wp(wp_id, lock_version=lock_version + 1)


@pytest.fixture
def tasks() -> list[WorkPackage]:
    return [_wp(1, 'Erstes'), _wp(2, 'Zweites'), _wp(3, 'Drittes')]


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def app_factory(
    tasks: list[WorkPackage], client: FakeClient
) -> T.Callable[..., OpApp]:
    def _make() -> OpApp:
        return OpApp(tasks=tasks, config=_config(), client=client)

    return _make


class TestOpenClose:
    async def test_u_opens_modal(self, app_factory: T.Callable[..., OpApp]) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            assert isinstance(app.screen, UpdateModal)

    async def test_q_in_modal_returns_without_changes(
        self, app_factory: T.Callable[..., OpApp], client: FakeClient
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            await pilot.press('q')
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            assert client.updates == []


class TestApply:
    async def test_g_applies_to_selected_tasks(
        self, app_factory: T.Callable[..., OpApp], client: FakeClient
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            # Select tasks 1 and 3 (cursor starts at 1; space, down, down, space)
            await pilot.press('space')          # select 1
            await pilot.press('down', 'down')   # cursor → 3
            await pilot.press('space')          # select 3
            await pilot.press('u')              # open modal
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            # Preset the form directly (selection dialog interaction is UI-heavy;
            # we test the apply flow by setting the form state directly).
            modal.form.status_id = 2
            await pilot.press('g')
            await pilot.pause()

        assert len(client.updates) == 2
        updated_ids = {u[0] for u in client.updates}
        assert updated_ids == {1, 3}
        # All updates carry the status change.
        for _id, _lock, changes in client.updates:
            assert changes == {'_links': {'status': {'href': '/api/v3/statuses/2'}}}

    async def test_g_falls_back_to_cursor_when_nothing_selected(
        self, app_factory: T.Callable[..., OpApp], client: FakeClient
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('down')           # cursor → task 2
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            modal.form.status_id = 3
            await pilot.press('g')
            await pilot.pause()

        assert len(client.updates) == 1
        wp_id, _, changes = client.updates[0]
        assert wp_id == 2
        assert changes == {'_links': {'status': {'href': '/api/v3/statuses/3'}}}

    async def test_g_with_empty_form_is_noop(
        self, app_factory: T.Callable[..., OpApp], client: FakeClient
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            await pilot.press('g')
            await pilot.pause()
        assert client.updates == []
