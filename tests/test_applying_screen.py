from __future__ import annotations

import typing as T

import pytest

from op.config import Config, ConnectionConfig, DefaultsConfig, RemoteConfig
from op.models import WorkPackage
from op.tui.app import OpApp
from op.tui.applying_screen import ApplyingScreen
from op.tui.main_screen import MainScreen
from op.tui.review_screen import ReviewScreen
from op.tui.update_form import UpdateForm


def _wp(id: int, subject: str = 's') -> WorkPackage:
    return WorkPackage(
        id=id, subject=subject, type_id=1, type_name='Task',
        status_id=1, status_name='Neu', project_id=10, project_name='W',
        lock_version=1,
    )


def _config() -> Config:
    return Config(
        connection=ConnectionConfig(base_url='https://op.example.com'),
        defaults=DefaultsConfig(),
        remote=RemoteConfig(
            statuses={1: 'Neu', 2: 'In Bearbeitung'},
            types={1: 'Task'},
            priorities={8: 'Normal'},
            users={5: 'Max'},
        ),
    )


class SuccessClient:
    def __init__(self) -> None:
        self.updates: list = []
        self.added_watchers: list = []
        self.removed_watchers: list = []

    async def update_work_package(
        self, wp_id: int, *, lock_version: int, changes: dict
    ) -> WorkPackage:
        self.updates.append((wp_id, lock_version, changes))
        return _wp(wp_id)

    async def add_watcher(self, wp_id: int, user_id: int) -> None:
        self.added_watchers.append((wp_id, user_id))

    async def remove_watcher(self, wp_id: int, user_id: int) -> None:
        self.removed_watchers.append((wp_id, user_id))


class FailingClient:
    def __init__(self, fail_ids: set[int]) -> None:
        self.fail_ids = fail_ids
        self.updates: list = []

    async def update_work_package(
        self, wp_id: int, *, lock_version: int, changes: dict
    ) -> WorkPackage:
        self.updates.append((wp_id, lock_version, changes))
        if wp_id in self.fail_ids:
            raise RuntimeError(f'Task {wp_id} is locked')
        return _wp(wp_id)

    async def add_watcher(self, wp_id: int, user_id: int) -> None:
        pass

    async def remove_watcher(self, wp_id: int, user_id: int) -> None:
        pass


@pytest.fixture
def tasks() -> list[WorkPackage]:
    return [_wp(1, 'Erstes'), _wp(2, 'Zweites'), _wp(3, 'Drittes')]


@pytest.fixture
def app_factory(
    tasks: list[WorkPackage],
) -> T.Callable[..., OpApp]:
    def _make(client=None) -> OpApp:  # noqa: ANN001
        app = OpApp(tasks=tasks, config=_config(), client=client or SuccessClient())
        for tid in (1, 2, 3):
            form = UpdateForm()
            form.status_id = 2
            app.pending_ops.add_or_merge(tid, form, original_subject=f'Task {tid}')
        return app

    return _make


class TestSuccessfulRun:
    async def test_all_ops_executed_and_queue_cleared(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('g')  # Selector → Review
            await pilot.pause()
            await pilot.press('g')  # Review → Applying
            # Let the worker finish
            for _ in range(20):
                await pilot.pause()
                if app.pending_ops.count == 0:
                    break

        assert app.pending_ops.count == 0
        assert len(app._client.updates) == 3  # type: ignore[attr-defined]

    async def test_auto_close_returns_to_selector_after_success(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('g')
            await pilot.pause()
            await pilot.press('g')
            for _ in range(20):
                await pilot.pause()
                if isinstance(app.screen, MainScreen):
                    break
            assert isinstance(app.screen, MainScreen)


class TestFailureRun:
    async def test_failure_message_appears_in_error_log(
        self, tasks: list
    ) -> None:
        """Regression: the failure message must be visible to the user, not silently logged."""
        from textual.widgets import RichLog

        client = FailingClient(fail_ids={2})
        app = OpApp(tasks=tasks, config=_config(), client=client)
        for tid in (1, 2, 3):
            form = UpdateForm()
            form.status_id = 2
            app.pending_ops.add_or_merge(tid, form, original_subject=f'T{tid}')

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('g')
            await pilot.pause()
            await pilot.press('g')
            for _ in range(20):
                await pilot.pause()
                screen = app.screen
                if isinstance(screen, ApplyingScreen) and screen.is_done:
                    break
            log = app.screen.query_one('#applying-errors', RichLog)
            # Error log is visible and contains the failure message
            assert 'visible' in log.classes
            # RichLog stores content as lines
            rendered = ''.join(str(line) for line in log.lines)
            assert 'OP#2' in rendered
            assert 'locked' in rendered or 'Task 2' in rendered

    async def test_failures_keep_screen_open_and_leave_failed_ops_in_queue(
        self, tasks: list
    ) -> None:
        client = FailingClient(fail_ids={2})
        app = OpApp(tasks=tasks, config=_config(), client=client)
        for tid in (1, 2, 3):
            form = UpdateForm()
            form.status_id = 2
            app.pending_ops.add_or_merge(tid, form, original_subject=f'T{tid}')

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('g')
            await pilot.pause()
            await pilot.press('g')
            for _ in range(20):
                await pilot.pause()
                screen = app.screen
                if (
                    isinstance(screen, ApplyingScreen)
                    and screen.is_done
                ):
                    break
            # Screen must still be ApplyingScreen (not auto-popped)
            assert isinstance(app.screen, ApplyingScreen)
            # Queue has the one failed op still
            assert app.pending_ops.count == 1
            assert app.pending_ops.get(2) is not None
            assert app.pending_ops.get(2).status == 'failed'
            # q returns to review (pop 1×)
            await pilot.press('q')
            await pilot.pause()
            assert isinstance(app.screen, ReviewScreen)


class TestWatcherApply:
    async def test_watcher_only_op_skips_patch(self, tasks: list[WorkPackage]) -> None:
        client = SuccessClient()
        app = OpApp(tasks=tasks, config=_config(), client=client)
        form = UpdateForm()
        form.add_watcher(7)
        app.pending_ops.add_or_merge(1, form, original_subject='Task 1')

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('g')
            await pilot.pause()
            await pilot.press('g')
            for _ in range(20):
                await pilot.pause()
                if app.pending_ops.count == 0:
                    break

        assert len(client.updates) == 0
        assert (1, 7) in client.added_watchers

    async def test_patch_and_watcher_op_calls_both(self, tasks: list[WorkPackage]) -> None:
        client = SuccessClient()
        app = OpApp(tasks=tasks, config=_config(), client=client)
        form = UpdateForm()
        form.status_id = 2
        form.add_watcher(7)
        app.pending_ops.add_or_merge(1, form, original_subject='Task 1')

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('g')
            await pilot.pause()
            await pilot.press('g')
            for _ in range(20):
                await pilot.pause()
                if app.pending_ops.count == 0:
                    break

        assert len(client.updates) == 1
        assert (1, 7) in client.added_watchers

    async def test_remove_watcher_called_during_apply(self, tasks: list[WorkPackage]) -> None:
        client = SuccessClient()
        app = OpApp(tasks=tasks, config=_config(), client=client)
        form = UpdateForm()
        form.remove_watcher(5)
        app.pending_ops.add_or_merge(1, form, original_subject='Task 1')

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('g')
            await pilot.pause()
            await pilot.press('g')
            for _ in range(20):
                await pilot.pause()
                if app.pending_ops.count == 0:
                    break

        assert (1, 5) in client.removed_watchers


class TestEmptyQueue:
    async def test_no_ops_returns_to_selector(
        self, tasks: list
    ) -> None:
        app = OpApp(tasks=tasks, config=_config(), client=SuccessClient())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(
                ApplyingScreen(config=_config(), client=app._client)
            )
            for _ in range(10):
                await pilot.pause()
                if isinstance(app.screen, MainScreen):
                    break
            assert isinstance(app.screen, MainScreen)
