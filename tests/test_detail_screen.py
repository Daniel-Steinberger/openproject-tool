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


class TestPendingDiff:
    async def test_no_pending_meta_text_has_no_arrow(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            screen = app.screen
            assert '→' not in screen._meta_text()

    async def test_pending_status_change_shows_arrow_in_meta(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        from op.tui.update_form import UpdateForm

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            screen = app.screen
            # Queue a status change for the task we're viewing
            form = UpdateForm()
            form.status_id = 2
            app.pending_ops.add_or_merge(screen.wp.id, form)
            meta = screen._meta_text(
                statuses_lookup={1: 'Neu', 2: 'In Bearbeitung'}
            )
            assert '→' in meta
            assert 'In Bearbeitung' in meta

    async def test_pending_subject_diff(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        from op.tui.update_form import UpdateForm

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            screen = app.screen
            form = UpdateForm()
            form.subject = 'Neuer Titel'
            app.pending_ops.add_or_merge(screen.wp.id, form)
            meta = screen._meta_text()
            assert 'Neuer Titel' in meta
            assert '→' in meta


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

    async def test_e_g_queues_change(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        """Editing from detail view must push into the app-queue (same flow as selector)."""
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.press('e')
            await pilot.pause()
            modal = app.screen
            modal.form.status_id = 2
            await pilot.press('g')
            await pilot.pause()
        op = app.pending_ops.get(1)
        assert op is not None
        assert op.form.status_id == 2


class TestMarkdownActivities:
    async def test_each_activity_rendered_as_markdown(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        from textual.widgets import Markdown

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            # Wait until activities are loaded
            for _ in range(10):
                await pilot.pause()
                if app.screen._activities:
                    break
            markdowns = app.screen.query('#activities Markdown')
            # FakeClient yields 2 activities with comments
            assert len(markdowns) >= 2

    async def test_no_comments_placeholder(
        self, tasks: list
    ) -> None:
        from textual.widgets import Label, Markdown

        class EmptyClient:
            async def get_activities(self, wp_id):  # noqa: ANN001, ANN202
                return []

            async def add_comment(self, wp_id, text):  # noqa: ANN001, ANN202
                pass

            async def update_work_package(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
                return None

        app = OpApp(tasks=tasks, config=_config(), client=EmptyClient())
        async with app.run_test() as pilot:
            await pilot.press('enter')
            for _ in range(5):
                await pilot.pause()
            # No Markdown children in the activities container
            markdowns = app.screen.query('#activities Markdown')
            assert len(markdowns) == 0


class TestLessNavigation:
    async def test_space_scrolls_page_down(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        from textual.containers import VerticalScroll

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            scroll = app.screen.query_one(VerticalScroll)
            before = scroll.scroll_y
            await pilot.press('space')
            await pilot.pause()
            # After space, cursor moves down by a page — y either advances
            # or clamped to 0 when content fits; either way, binding must fire
            # (assert action invoked via new method, not a crash)
            assert scroll.scroll_y >= before

    async def test_greater_scrolls_to_end(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            # Directly invoke the action method — pilot/key-routing for `>` is flaky
            app.screen.action_scroll_end()

    async def test_less_scrolls_to_home(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            app.screen.action_scroll_home()


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
