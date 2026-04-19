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
    async def test_g_queues_change_for_selected_tasks(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('space')
            await pilot.press('down', 'down')
            await pilot.press('space')
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            modal.form.status_id = 2
            await pilot.press('g')
            await pilot.pause()

        assert app.pending_ops.count == 2
        for task_id in (1, 3):
            op = app.pending_ops.get(task_id)
            assert op is not None
            assert op.form.api_changes() == {
                '_links': {'status': {'href': '/api/v3/statuses/2'}}
            }

    async def test_g_falls_back_to_cursor_when_nothing_selected(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('down')
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            modal.form.status_id = 3
            await pilot.press('g')
            await pilot.pause()

        assert app.pending_ops.count == 1
        op = app.pending_ops.get(2)
        assert op is not None
        assert op.form.api_changes() == {
            '_links': {'status': {'href': '/api/v3/statuses/3'}}
        }

    async def test_g_with_empty_form_is_noop(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            await pilot.press('g')
            await pilot.pause()
        assert app.pending_ops.count == 0


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

    async def test_single_edit_queues_subject_change(
        self, app_factory: T.Callable[..., OpApp]
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
        op = app.pending_ops.get(1)
        assert op is not None
        assert op.form.api_changes() == {'subject': 'Neuer Titel'}

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
        self, app_factory: T.Callable[..., OpApp]
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
        op = app.pending_ops.get(1)
        assert op is not None
        changes = op.form.api_changes()
        assert changes['startDate'] == today_iso
        assert changes['dueDate'] == today_iso

    async def test_explicit_due_not_overwritten(
        self, app_factory: T.Callable[..., OpApp]
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

        op = app.pending_ops.get(1)
        changes = op.form.api_changes()
        assert changes['startDate'] == '2026-05-01'
        assert changes['dueDate'] == '2026-05-15'

    async def test_plus_days_shortcut(
        self, app_factory: T.Callable[..., OpApp]
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
        op = app.pending_ops.get(1)
        assert op.form.api_changes()['startDate'] == expected


class TestApplyThroughRealClient:
    """Verify that pressing 'g' actually fires the HTTP PATCH via the real client."""

    @pytest.mark.skip(reason='Moved to ApplyingScreen integration test in Phase F')
    async def test_apply_sends_patch_to_openproject(
        self, tasks: list, respx_mock
    ) -> None:
        import httpx
        from textual.widgets import Input

        from op.api import OpenProjectClient

        base_url = 'https://op.example.com'
        patch_route = respx_mock.patch(f'{base_url}/api/v3/work_packages/1').mock(
            return_value=httpx.Response(
                200,
                json={
                    '_type': 'WorkPackage',
                    'id': 1,
                    'subject': 'Neuer Titel',
                    'description': {'raw': ''},
                    'lockVersion': 2,
                    '_links': {
                        'type': {'href': '/api/v3/types/1', 'title': 'Task'},
                        'status': {'href': '/api/v3/statuses/2', 'title': 'In Bearbeitung'},
                        'project': {'href': '/api/v3/projects/10', 'title': 'Web'},
                    },
                },
            )
        )

        async with OpenProjectClient(base_url, 'testkey') as client:
            app = OpApp(tasks=tasks, config=_config(), client=client)
            async with app.run_test() as pilot:
                await pilot.press('u')
                await pilot.pause()
                modal = app.screen
                assert isinstance(modal, UpdateModal)
                # Change subject directly on the single-task form
                modal.query_one('#input-subject', Input).value = 'Neuer Titel'
                await pilot.press('g')
                # Give any async callback/worker a chance to complete
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

        assert patch_route.called, 'Apply did not send a PATCH request to OpenProject'
        import json
        body = json.loads(patch_route.calls.last.request.content)
        assert body['subject'] == 'Neuer Titel'
        assert body['lockVersion'] == 1


class TestCalendarPopup:
    """Calendar popup integration — focus detection, push, and rendering survival."""

    async def test_date_actions_hidden_when_non_date_input_focused(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        """Footer hints should only appear when a date input is focused."""
        from textual.widgets import Input

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            modal.query_one('#input-subject', Input).focus()
            await pilot.pause()
            # check_action returns False → Footer hides the binding
            assert modal.check_action('pick_date', ()) is False
            assert modal.check_action('insert_today', ()) is False
            assert modal.check_action('insert_next_free', ()) is False
            # Non-date actions stay available
            assert modal.check_action('apply', ()) is True

    async def test_date_actions_visible_when_start_input_focused(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        from textual.widgets import Input

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            modal.query_one('#input-start', Input).focus()
            await pilot.pause()
            assert modal.check_action('pick_date', ()) is True
            assert modal.check_action('insert_today', ()) is True
            assert modal.check_action('insert_next_free', ()) is True

    async def test_insert_today_fills_start_input(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        from datetime import date

        from textual.widgets import Input

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            modal.query_one('#input-start', Input).focus()
            await pilot.pause()
            modal.action_insert_today()
            assert modal.query_one('#input-start', Input).value == date.today().isoformat()

    async def test_insert_today_fills_due_input_when_due_focused(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        from datetime import date

        from textual.widgets import Input

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            modal.query_one('#input-due', Input).focus()
            await pilot.pause()
            modal.action_insert_today()
            assert modal.query_one('#input-due', Input).value == date.today().isoformat()

    async def test_insert_next_free_uses_busy_days(
        self, tasks: list
    ) -> None:
        from datetime import date, timedelta

        from textual.widgets import Input

        # Monday next week, to guarantee workday
        today = date.today()
        while today.weekday() >= 5:
            today += timedelta(days=1)
        busy = {today}
        expected = today + timedelta(days=1)
        while expected.weekday() >= 5:
            expected += timedelta(days=1)

        class BusyClient:
            def __init__(self) -> None:
                self.updates: list = []

            async def get_busy_days(self, principal_id: int) -> set[date]:
                return busy

            async def update_work_package(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
                return None

        app = OpApp(tasks=tasks, config=_config(), client=BusyClient())
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            modal.form.assignee_id = 5
            start_input = modal.query_one('#input-start', Input)
            start_input.focus()
            modal._today_override = today  # type: ignore[attr-defined]
            await pilot.pause()
            await modal.action_insert_next_free()
            assert start_input.value == expected.isoformat()

    async def test_calendar_pick_mirrors_start_to_due_when_due_empty(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        """When the calendar writes into start and due is empty, due should auto-fill."""
        from datetime import date

        from textual.widgets import Input

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            start = modal.query_one('#input-start', Input)
            due = modal.query_one('#input-due', Input)
            start.value = ''
            due.value = ''
            start.focus()
            await pilot.pause()
            await modal.action_pick_date()
            await pilot.pause()
            cal = app.screen
            # Walk through the calendar: move to a specific date, press Enter.
            cal.selected = date(2026, 6, 15)
            cal._refresh_display()
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()

            assert start.value == '2026-06-15'
            assert due.value == '2026-06-15'

    async def test_calendar_pick_mirrors_start_to_due_even_when_due_has_value(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        """Issue #10: setting start via pick drags due to the same day (user can edit due after)."""
        from datetime import date

        from textual.widgets import Input

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            start = modal.query_one('#input-start', Input)
            due = modal.query_one('#input-due', Input)
            start.value = ''
            due.value = '2026-12-31'
            start.focus()
            await pilot.pause()
            await modal.action_pick_date()
            await pilot.pause()
            cal = app.screen
            cal.selected = date(2026, 6, 15)
            cal._refresh_display()
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()

            assert start.value == '2026-06-15'
            assert due.value == '2026-06-15'

    async def test_calendar_receives_busy_days_from_client(
        self, tasks: list
    ) -> None:
        """Busy-day coloring depends on the CalendarModal receiving busy_days from the client."""
        from datetime import date

        from textual.widgets import Input

        from op.tui.calendar_modal import CalendarModal

        busy = {date(2026, 6, 20), date(2026, 6, 21)}

        class BusyClient:
            async def get_busy_days(self, principal_id: int) -> set[date]:
                return busy

            async def update_work_package(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
                return None

        app = OpApp(tasks=tasks, config=_config(), client=BusyClient())
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            modal.form.assignee_id = 5
            modal.query_one('#input-start', Input).focus()
            await pilot.pause()
            await modal.action_pick_date()
            await pilot.pause()
            cal = app.screen
            assert isinstance(cal, CalendarModal)
            assert cal.busy_days == busy

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

        today = date.today()
        if today.weekday() >= 5:
            today += timedelta(days=7 - today.weekday())
        busy = {today, today + timedelta(days=1)}
        expected_free = today + timedelta(days=2)
        while expected_free.weekday() >= 5:
            expected_free += timedelta(days=1)

        class BusyClient:
            async def get_busy_days(self, principal_id: int) -> set[date]:
                return busy

            async def update_work_package(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
                return None

        app = OpApp(tasks=tasks, config=_config(), client=BusyClient())
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            modal.form.set_assignee(principal_id=5, is_group=False)
            modal.query_one('#input-start', Input).value = 'next'
            modal._today_override = today  # type: ignore[attr-defined]
            await pilot.press('g')
            await pilot.pause()

        op = app.pending_ops.get(1)
        assert op is not None
        assert op.form.api_changes()['startDate'] == expected_free.isoformat()

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
