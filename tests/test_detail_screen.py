from __future__ import annotations

import typing as T

import pytest

from op.config import Config, ConnectionConfig, DefaultsConfig, RemoteConfig
from op.models import Activity, WorkPackage
from op.tui.app import OpApp
from op.tui.detail_screen import DetailScreen
from op.tui.main_screen import MainScreen
from op.tui.update_modal import UpdateModal


def _wp(id: int, subject: str = 'S', description: str | None = None) -> WorkPackage:
    return WorkPackage(
        id=id,
        subject=subject,
        description=description,
        type_id=1,
        type_name='Task',
        status_id=1,
        status_name='Neu',
        project_id=10,
        project_name='Web',
        lock_version=1,
    )


class FakeClient:
    def __init__(self) -> None:
        self.added_comments: list[tuple[int, str]] = []
        self.updates: list[tuple[int, int, dict]] = []

    async def get_activities(self, wp_id: int) -> list[Activity]:
        return [
            Activity(id=1, comment='Erster Kommentar', user_name='Max'),
            Activity(id=2, comment='Zweiter Kommentar', user_name='Anna'),
        ]

    async def add_comment(self, wp_id: int, text: str) -> None:
        self.added_comments.append((wp_id, text))

    async def update_work_package(
        self, wp_id: int, *, lock_version: int, changes: dict
    ) -> WorkPackage:
        self.updates.append((wp_id, lock_version, changes))
        return _wp(wp_id)


def _config() -> Config:
    return Config(
        connection=ConnectionConfig(base_url='https://op.example.com'),
        defaults=DefaultsConfig(),
        remote=RemoteConfig(
            statuses={1: 'Neu', 2: 'In Bearbeitung'},
            types={1: 'Task', 2: 'Bug'},
            priorities={8: 'Normal'},
            users={5: 'Max'},
        ),
    )


@pytest.fixture
def tasks() -> list[WorkPackage]:
    return [
        _wp(1, 'Erster Task', description='Beschreibung für Task 1'),
        _wp(2, 'Zweiter Task'),
    ]


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
    async def test_enter_opens_detail(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            assert isinstance(app.screen, DetailScreen)
            assert app.screen.wp.id == 1

    async def test_detail_reflects_cursor_row(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('down')
            await pilot.press('enter')
            await pilot.pause()
            assert isinstance(app.screen, DetailScreen)
            assert app.screen.wp.id == 2

    async def test_q_returns_to_main(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('q')
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)


class TestEdit:
    async def test_e_opens_update_for_current_task_only(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.press('e')
            await pilot.pause()
            assert isinstance(app.screen, UpdateModal)


class TestOpenInBrowser:
    async def test_o_opens_current_task_in_browser(
        self, app_factory: T.Callable[..., OpApp], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        opened: list[str] = []
        monkeypatch.setattr('webbrowser.open', lambda url: opened.append(url))
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('o')
            await pilot.pause()
        assert opened == ['https://op.example.com/work_packages/1']


class TestComment:
    async def test_c_opens_comment_modal(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.press('c')
            await pilot.pause()
            from op.tui.comment_modal import CommentModal

            assert isinstance(app.screen, CommentModal)

    async def test_comment_submit_calls_client(
        self, app_factory: T.Callable[..., OpApp], client: FakeClient
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.press('c')
            await pilot.pause()
            from op.tui.comment_modal import CommentModal

            modal = app.screen
            assert isinstance(modal, CommentModal)
            modal.text = 'Hallo vom Test'
            await pilot.press('ctrl+s')
            await pilot.pause()
        assert client.added_comments == [(1, 'Hallo vom Test')]
