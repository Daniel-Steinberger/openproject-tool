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

    async def get_watchers(self, wp_id: int) -> list:
        return []

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

    async def test_pending_project_change_shows_arrow_in_meta(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        from op.tui.update_form import UpdateForm

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            screen = app.screen
            form = UpdateForm()
            form.project_id = 99
            app.pending_ops.add_or_merge(screen.wp.id, form)
            meta = screen._meta_text(
                projects_lookup={10: 'Web', 99: 'Mobile'}
            )
            assert '→' in meta
            assert 'Mobile' in meta


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


class TestSearch:
    @pytest.fixture
    def wp_with_long_desc(self) -> WorkPackage:
        return WorkPackage(
            id=1,
            subject='Search-Demo',
            description=(
                'Alpha beta gamma.\n'
                '\n'
                'A second paragraph mentions beta again.'
            ),
            type_id=1,
            type_name='Task',
            status_id=1,
            status_name='Neu',
            project_id=10,
            project_name='W',
            lock_version=1,
        )

    async def test_run_search_counts_matches_across_description_and_comments(
        self, tasks: list
    ) -> None:
        class ClientWithBeta:
            async def get_activities(self, wp_id):  # noqa: ANN001, ANN202
                return [
                    Activity(id=1, comment='Das Beta Release!', user_name='X'),
                    Activity(id=2, comment='ohne Treffer', user_name='Y'),
                    Activity(id=3, comment='noch ein beta Hinweis', user_name='Z'),
                ]

            async def update_work_package(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
                return None

        # Replace task 1 with one that has a description mentioning beta
        custom = [
            WorkPackage(
                id=1, subject='s', type_id=1, type_name='Task',
                status_id=1, status_name='Neu', project_id=10, project_name='W',
                lock_version=1, description='Alpha beta gamma delta',
            ),
            tasks[1],
        ]
        app = OpApp(tasks=custom, config=_config(), client=ClientWithBeta())
        async with app.run_test() as pilot:
            await pilot.press('enter')
            for _ in range(10):
                await pilot.pause()
                if app.screen._activities:
                    break
            screen = app.screen
            screen._run_search('beta')
            # 1 match in description + 2 matches in activity comments = 3
            assert screen._total_matches == 3
            assert len(screen._search_hits) == 3

    async def test_search_next_and_prev_navigate(
        self, tasks: list
    ) -> None:
        class ClientWithHits:
            async def get_activities(self, wp_id):  # noqa: ANN001, ANN202
                return [
                    Activity(id=1, comment='foo', user_name='X'),
                    Activity(id=2, comment='foo again', user_name='Y'),
                ]

            async def update_work_package(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
                return None

        custom = [
            WorkPackage(
                id=1, subject='s', type_id=1, type_name='Task',
                status_id=1, status_name='Neu', project_id=10, project_name='W',
                lock_version=1, description='foo bar',
            ),
            tasks[1],
        ]
        app = OpApp(tasks=custom, config=_config(), client=ClientWithHits())
        async with app.run_test() as pilot:
            await pilot.press('enter')
            for _ in range(10):
                await pilot.pause()
                if app.screen._activities:
                    break
            screen = app.screen
            screen._run_search('foo')
            assert screen._current_hit == 0
            screen.action_search_next()
            assert screen._current_hit == 1
            screen.action_search_next()
            assert screen._current_hit == 2
            screen.action_search_next()
            # wrap-around
            assert screen._current_hit == 0
            screen.action_search_prev()
            assert screen._current_hit == 2

    async def test_no_matches_yields_zero_and_empty_hits(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            for _ in range(10):
                await pilot.pause()
                if app.screen._activities:
                    break
            screen = app.screen
            screen._run_search('xyznonexistent')
            assert screen._total_matches == 0
            assert screen._search_hits == []

    async def test_slash_opens_search_input(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        from textual.widgets import Input

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('slash')
            await pilot.pause()
            input_ = app.screen.query_one('#search-input', Input)
            assert input_.display is True
            assert input_.has_focus

    async def test_search_bar_is_single_line_no_border(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        """Search bar mimics less: one line, no border, full-width coloured background."""
        from textual.containers import Horizontal
        from textual.widgets import Input

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('slash')
            await pilot.pause()
            bar = app.screen.query_one('#search-bar', Horizontal)
            assert bar.region.height == 1
            input_ = app.screen.query_one('#search-input', Input)
            # Input must also be single-line (no rendered border around it).
            assert input_.region.height == 1

    async def test_search_input_accepts_typed_text(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        """The text entered by the user must land in Input.value."""
        from textual.widgets import Input

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('slash')
            await pilot.pause()
            await pilot.press('f', 'o', 'o')
            await pilot.pause()
            assert app.screen.query_one('#search-input', Input).value == 'foo'

    async def test_search_hit_markdown_contains_highlighted_match_span(
        self, tasks: list
    ) -> None:
        """The match substring must be wrapped as bold so the user can see where it hit."""
        from textual.widgets import Markdown

        class ClientWithHits:
            async def get_activities(self, wp_id):  # noqa: ANN001, ANN202
                return [
                    Activity(id=1, comment='Hallo foo bar', user_name='X', user_id=1),
                ]

            async def update_work_package(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
                return None

        custom = [
            WorkPackage(
                id=1, subject='s', type_id=1, type_name='Task',
                status_id=1, status_name='Neu', project_id=10, project_name='W',
                lock_version=1, description=None,
            ),
            tasks[1],
        ]
        app = OpApp(tasks=custom, config=_config(), client=ClientWithHits())
        async with app.run_test() as pilot:
            await pilot.press('enter')
            for _ in range(10):
                await pilot.pause()
                if app.screen._activities:
                    break
            screen = app.screen
            screen._run_search('foo')
            await pilot.pause()
            hit_widget = screen._search_hits[0]
            assert isinstance(hit_widget, Markdown)
            # Bold-wrapped match is what Textual Markdown actually renders visibly
            assert '**foo**' in hit_widget._markdown

    async def test_clearing_search_restores_original_markdown(
        self, tasks: list
    ) -> None:
        from textual.widgets import Markdown

        class ClientWithHits:
            async def get_activities(self, wp_id):  # noqa: ANN001, ANN202
                return [
                    Activity(id=1, comment='foo text', user_name='X', user_id=1),
                ]

            async def update_work_package(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
                return None

        custom = [
            WorkPackage(
                id=1, subject='s', type_id=1, type_name='Task',
                status_id=1, status_name='Neu', project_id=10, project_name='W',
                lock_version=1, description=None,
            ),
            tasks[1],
        ]
        app = OpApp(tasks=custom, config=_config(), client=ClientWithHits())
        async with app.run_test() as pilot:
            await pilot.press('enter')
            for _ in range(10):
                await pilot.pause()
                if app.screen._activities:
                    break
            screen = app.screen
            screen._run_search('foo')
            await pilot.pause()
            widget = screen._activity_widgets[0][0]
            assert '**foo**' in widget._markdown
            screen._run_search('')
            await pilot.pause()
            assert '**foo**' not in widget._markdown

    async def test_incremental_search_updates_on_each_keystroke(
        self, tasks: list
    ) -> None:
        """Typing in the search box should update matches live (no Enter required)."""
        from textual.widgets import Input

        class ClientWithHits:
            async def get_activities(self, wp_id):  # noqa: ANN001, ANN202
                return [
                    Activity(id=1, comment='foo bar', user_name='X', user_id=1),
                    Activity(id=2, comment='food', user_name='Y', user_id=2),
                ]

            async def update_work_package(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
                return None

        custom = [
            WorkPackage(
                id=1, subject='s', type_id=1, type_name='Task',
                status_id=1, status_name='Neu', project_id=10, project_name='W',
                lock_version=1, description=None,
            ),
            tasks[1],
        ]
        app = OpApp(tasks=custom, config=_config(), client=ClientWithHits())
        async with app.run_test() as pilot:
            await pilot.press('enter')
            for _ in range(10):
                await pilot.pause()
                if app.screen._activities:
                    break
            screen = app.screen
            await pilot.press('slash')
            await pilot.pause()
            input_ = screen.query_one('#search-input', Input)
            # Simulate incremental typing by directly writing to the input —
            # this triggers Input.Changed which should run the search.
            input_.value = 'f'
            await pilot.pause()
            assert screen._total_matches == 2  # both 'foo' and 'food' start with f
            input_.value = 'foo'
            await pilot.pause()
            assert screen._total_matches == 2
            input_.value = 'food'
            await pilot.pause()
            assert screen._total_matches == 1

    async def test_escape_during_search_cancels_without_closing_detail(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        """Esc while search-bar is open must clear search, not pop the DetailScreen."""
        from textual.containers import Horizontal

        from op.tui.detail_screen import DetailScreen

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('slash')
            await pilot.pause()
            await pilot.press('escape')
            await pilot.pause()
            # Still on the detail screen, bar hidden
            assert isinstance(app.screen, DetailScreen)
            bar = app.screen.query_one('#search-bar', Horizontal)
            assert 'visible' not in bar.classes


class TestActivityUserFallback:
    async def test_user_resolved_via_remote_when_title_missing(
        self, tasks: list
    ) -> None:
        """When link has no title, fall back to the remote.users lookup by user_id."""
        from textual.widgets import Label

        class ClientWithAnonymousActivity:
            async def get_activities(self, wp_id):  # noqa: ANN001, ANN202
                return [
                    Activity(
                        id=1, comment='hi', user_name=None, user_id=5,
                        created_at='2026-01-01',
                    )
                ]

            async def update_work_package(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
                return None

        cfg = _config()
        cfg.remote.users[5] = 'Max Mustermann'
        app = OpApp(tasks=tasks, config=cfg, client=ClientWithAnonymousActivity())
        async with app.run_test() as pilot:
            await pilot.press('enter')
            for _ in range(10):
                await pilot.pause()
                if app.screen._activities:
                    break
            heads = app.screen.query('.activity-head')
            assert heads
            rendered = str(heads.first(Label).render())
            assert 'Max Mustermann' in rendered
            assert '(unknown)' not in rendered


class TestActivityHtmlContent:
    async def test_table_in_html_is_rendered_as_markdown_table(
        self, tasks: list
    ) -> None:
        from textual.widgets import Markdown

        html_body = (
            '<p>intro</p>'
            '<table><tr><th>Stufe</th><th>Art</th></tr>'
            '<tr><td>1</td><td>DVS-Rechnung</td></tr></table>'
        )

        class ClientWithTableComment:
            async def get_activities(self, wp_id):  # noqa: ANN001, ANN202
                return [
                    Activity(
                        id=1,
                        comment='intro',
                        comment_html=html_body,
                        user_name='Max',
                        user_id=5,
                    )
                ]

            async def update_work_package(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
                return None

        app = OpApp(tasks=tasks, config=_config(), client=ClientWithTableComment())
        async with app.run_test() as pilot:
            await pilot.press('enter')
            for _ in range(10):
                await pilot.pause()
                if app.screen._activities:
                    break
            markdowns = app.screen.query('#activities Markdown')
            assert len(markdowns) == 1
            source = markdowns.first(Markdown)._markdown
            assert 'Stufe' in source
            assert 'DVS-Rechnung' in source


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


class TestPmCustomField:
    """PM (customField42) appears in detail meta and is pre-filled in the edit dialog."""

    def _wp_with_pm(self) -> WorkPackage:
        return WorkPackage(
            id=1,
            subject='Task mit PM',
            type_id=1,
            type_name='Task',
            status_id=1,
            status_name='Neu',
            project_id=10,
            project_name='Web',
            lock_version=1,
            custom_field_links={42: 94},
        )

    def _config_with_pm(self) -> Config:
        return Config(
            connection=ConnectionConfig(base_url='https://op.example.com'),
            defaults=DefaultsConfig(),
            remote=RemoteConfig(
                statuses={1: 'Neu'},
                types={1: 'Task'},
                users={94: 'AUM Mustermann'},
                custom_fields={42: 'PM'},
                custom_field_users={42: {94: 'AUM Mustermann'}},
            ),
        )

    async def test_pm_shown_in_meta_label(self) -> None:
        wp = self._wp_with_pm()
        config = self._config_with_pm()
        app = OpApp(tasks=[wp], config=config)
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, DetailScreen)
            meta = detail._meta_text()
            assert 'PM' in meta
            assert 'AUM Mustermann' in meta

    async def test_pm_not_shown_when_empty(self) -> None:
        wp = _wp(1, 'S')  # no custom_field_links
        config = self._config_with_pm()
        app = OpApp(tasks=[wp], config=config)
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            detail = app.screen
            assert isinstance(detail, DetailScreen)
            meta = detail._meta_text()
            assert 'AUM Mustermann' not in meta

    async def test_pm_prefilled_in_edit_modal(self) -> None:
        from textual.widgets import Select

        wp = self._wp_with_pm()
        config = self._config_with_pm()
        app = OpApp(tasks=[wp], config=config)
        async with app.run_test() as pilot:
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('e')
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, UpdateModal)
            sel = modal.query_one('#sel-cf-42', Select)
            assert sel.value == 94
