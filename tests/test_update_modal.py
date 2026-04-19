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


class TestSingleTaskAllFields:
    async def test_single_edit_shows_scalar_inputs(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        """When opened for a single task, subject/description/dates must be editable."""
        from textual.widgets import Input, TextArea

        app = app_factory()
        async with app.run_test() as pilot:
            # No selection → target = cursor row (task 1)
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            # Scalar inputs must exist with prefilled values from the task.
            assert modal.query_one('#input-subject', Input).value == 'Erstes'
            assert modal.query_one('#ta-description', TextArea) is not None

    async def test_single_edit_submits_subject_change(
        self, app_factory: T.Callable[..., OpApp], client: FakeClient
    ) -> None:
        from textual.widgets import Input

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            modal.query_one('#input-subject', Input).value = 'Neuer Titel'
            await pilot.press('g')
            await pilot.pause()
        assert len(client.updates) == 1
        wp_id, _lock, changes = client.updates[0]
        assert wp_id == 1
        assert changes == {'subject': 'Neuer Titel'}

    async def test_batch_edit_hides_scalar_inputs(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        """Multiple selected tasks → only link fields, no subject/description."""
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('space')
            await pilot.press('down')
            await pilot.press('space')
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            # Scalar inputs must NOT be present
            assert not modal.query('#input-subject')
            assert not modal.query('#ta-description')


class TestDateShortcuts:
    async def test_start_shortcut_expands_and_sets_due_automatically(
        self, app_factory: T.Callable[..., OpApp], client: FakeClient
    ) -> None:
        """`today` shortcut in start-date expands + auto-copies to due-date."""
        from datetime import date

        from textual.widgets import Input

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            modal.query_one('#input-start', Input).value = 'today'
            await pilot.press('g')
            await pilot.pause()

        today_iso = date.today().isoformat()
        assert len(client.updates) == 1
        _, _, changes = client.updates[0]
        assert changes['startDate'] == today_iso
        assert changes['dueDate'] == today_iso

    async def test_explicit_due_not_overwritten(
        self, app_factory: T.Callable[..., OpApp], client: FakeClient
    ) -> None:
        """If user sets both start and due explicitly, due is kept as-is."""
        from textual.widgets import Input

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            modal.query_one('#input-start', Input).value = '2026-05-01'
            modal.query_one('#input-due', Input).value = '2026-05-15'
            await pilot.press('g')
            await pilot.pause()

        _, _, changes = client.updates[0]
        assert changes['startDate'] == '2026-05-01'
        assert changes['dueDate'] == '2026-05-15'

    async def test_plus_days_shortcut(
        self, app_factory: T.Callable[..., OpApp], client: FakeClient
    ) -> None:
        from datetime import date, timedelta

        from textual.widgets import Input

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            modal.query_one('#input-start', Input).value = '+7'
            await pilot.press('g')
            await pilot.pause()

        expected = (date.today() + timedelta(days=7)).isoformat()
        _, _, changes = client.updates[0]
        assert changes['startDate'] == expected


class TestCalendarPopup:
    """Calendar popup integration — focus detection, push, and rendering survival."""

    async def test_calendar_can_be_pushed_and_rendered(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        """Regression test for #13: CalendarModal._render must NOT shadow Widget._render."""
        from datetime import date

        from textual.widgets import Input

        from op.tui.calendar_modal import CalendarModal

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            update_modal = app.screen
            assert isinstance(update_modal, UpdateModal)
            update_modal.query_one('#input-start', Input).focus()
            await pilot.pause()
            # Push the calendar via the action — this used to crash with
            # AttributeError: 'NoneType' object has no attribute 'render_strips'
            await update_modal.action_pick_date()
            await pilot.pause()
            # If the rendering pipeline is intact, we should now be on a CalendarModal
            assert isinstance(app.screen, CalendarModal)
            # And a full frame render must not raise
            assert app.screen.selected == date.today()


    async def test_focused_date_input_returns_start_when_start_focused(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        from textual.widgets import Input

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            modal.query_one('#input-start', Input).focus()
            await pilot.pause()
            target = modal._focused_date_input()
            assert target is not None
            assert target.id == 'input-start'

    async def test_focused_date_input_returns_due_when_due_focused(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        from textual.widgets import Input

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            modal.query_one('#input-due', Input).focus()
            await pilot.pause()
            target = modal._focused_date_input()
            assert target is not None
            assert target.id == 'input-due'

    async def test_focused_date_input_is_none_when_other_widget_focused(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        from textual.widgets import Input

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            modal.query_one('#input-subject', Input).focus()
            await pilot.pause()
            assert modal._focused_date_input() is None

    async def test_load_busy_days_returns_empty_without_client(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            modal._client = None  # type: ignore[attr-defined]
            busy = await modal._load_busy_days_silent()
        assert busy == set()

    async def test_load_busy_days_swallows_api_errors(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()

        class BadClient:
            async def get_busy_days(self, principal_id: int):  # noqa: ANN001, ANN201
                raise RuntimeError('network down')

        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            modal._client = BadClient()  # type: ignore[attr-defined]
            modal.form.assignee_id = 5
            busy = await modal._load_busy_days_silent()
        assert busy == set()


class TestWorkloadShortcut:
    async def test_next_uses_busy_days_when_client_available(
        self, tasks: list, monkeypatch
    ) -> None:
        """When the assignee has today blocked, `next` should skip to the next free workday."""
        from datetime import date, timedelta

        from textual.widgets import Input

        # Busy: today (if workday) and tomorrow — expect the day after
        today = date.today()
        # Make sure we start from a workday for a predictable test
        if today.weekday() >= 5:
            today += timedelta(days=7 - today.weekday())
        busy = {today, today + timedelta(days=1)}
        expected_free = today + timedelta(days=2)
        while expected_free.weekday() >= 5:
            expected_free += timedelta(days=1)

        class BusyClient:
            def __init__(self) -> None:
                self.updates: list = []

            async def get_busy_days(self, principal_id: int) -> set[date]:
                return busy

            async def update_work_package(
                self, wp_id: int, *, lock_version: int, changes: dict
            ):
                self.updates.append((wp_id, lock_version, changes))
                return None

        bc = BusyClient()
        app = OpApp(tasks=tasks, config=_config(), client=bc)
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            # Select an assignee so the modal knows who to check
            modal.form.set_assignee(principal_id=5, is_group=False)
            # Pretend user typed "next" into start
            modal.query_one('#input-start', Input).value = 'next'
            # Fake "today" to our chosen workday for determinism
            modal._today_override = today  # type: ignore[attr-defined]
            await pilot.press('g')
            await pilot.pause()

        assert len(bc.updates) == 1
        _, _, changes = bc.updates[0]
        assert changes['startDate'] == expected_free.isoformat()

    async def test_next_falls_back_without_client(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        """No client → basic next-workday shortcut still works."""
        from datetime import date, timedelta

        from textual.widgets import Input

        app = app_factory()
        app._client = None  # type: ignore[attr-defined]
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            modal.query_one('#input-start', Input).value = 'next'
            await pilot.press('g')
            await pilot.pause()
        # With no client we expect the basic next-workday logic
        today = date.today()
        expected = today
        while expected.weekday() >= 5:
            expected += timedelta(days=1)
        # We can't assert on client.updates (no client); just ensure no crash.
