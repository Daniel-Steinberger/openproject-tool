from __future__ import annotations

import typing as T

import pytest

from op.config import Config, ConnectionConfig, DefaultsConfig, RemoteConfig
from op.models import WorkPackage
from op.tui.app import OpApp
from op.tui.main_screen import MainScreen


def _wp(id: int, subject: str = 'Subject', status: str = 'Neu') -> WorkPackage:
    return WorkPackage(
        id=id,
        subject=subject,
        type_id=1,
        type_name='Task',
        status_id=1,
        status_name=status,
        project_id=10,
        project_name='Web',
        lock_version=1,
    )


def _config() -> Config:
    return Config(
        connection=ConnectionConfig(base_url='https://op.example.com'),
        defaults=DefaultsConfig(),
        remote=RemoteConfig(),
    )


@pytest.fixture
def tasks() -> list[WorkPackage]:
    return [_wp(1, 'Erstes'), _wp(2, 'Zweites'), _wp(3, 'Drittes')]


@pytest.fixture
def app_factory(tasks: list[WorkPackage]) -> T.Callable[..., OpApp]:
    def _make(custom_tasks: list[WorkPackage] | None = None) -> OpApp:
        return OpApp(tasks=custom_tasks if custom_tasks is not None else tasks, config=_config())

    return _make


class TestInitialState:
    async def test_main_screen_mounts_with_all_tasks(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, MainScreen)
            assert len(screen.tasks) == 3
            assert screen.selection.count == 0


class TestSelection:
    async def test_space_selects_cursor_row(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('space')
            await pilot.pause()
            screen: MainScreen = app.screen  # type: ignore[assignment]
            assert screen.selection.contains(1)
            assert screen.selection.count == 1

    async def test_space_toggle_deselects(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('space')
            await pilot.press('space')
            await pilot.pause()
            screen: MainScreen = app.screen  # type: ignore[assignment]
            assert screen.selection.count == 0

    async def test_down_moves_cursor_before_select(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('down')
            await pilot.press('space')
            await pilot.pause()
            screen: MainScreen = app.screen  # type: ignore[assignment]
            assert screen.selection.contains(2)
            assert not screen.selection.contains(1)

    async def test_invert_selects_all_when_none_selected(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('i')
            await pilot.pause()
            screen: MainScreen = app.screen  # type: ignore[assignment]
            assert screen.selection.count == 3

    async def test_invert_flips_existing(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('space')  # select 1
            await pilot.press('i')       # invert → {2, 3}
            await pilot.pause()
            screen: MainScreen = app.screen  # type: ignore[assignment]
            assert not screen.selection.contains(1)
            assert screen.selection.contains(2)
            assert screen.selection.contains(3)


class TestQuit:
    async def test_q_exits_app(self, app_factory: T.Callable[..., OpApp]) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('q')
            await pilot.pause()
        assert app._exit


class TestQueueIntegration:
    async def test_u_then_g_queues_change_instead_of_applying_directly(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        """After 'u' → changes in modal → 'g', the op should be in the queue, not sent to API."""
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('u')
            await pilot.pause()
            # Change status via the form directly
            modal = app.screen
            modal.form.status_id = 2
            await pilot.press('g')
            await pilot.pause()
        assert app.pending_ops.count == 1
        op = app.pending_ops.get(1)
        assert op is not None
        assert op.form.status_id == 2

    async def test_second_edit_merges_fields_in_queue(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            # First edit: set status
            await pilot.press('u')
            await pilot.pause()
            app.screen.form.status_id = 2
            await pilot.press('g')
            await pilot.pause()
            # Second edit on same task: set priority
            await pilot.press('u')
            await pilot.pause()
            app.screen.form.priority_id = 9
            await pilot.press('g')
            await pilot.pause()
        op = app.pending_ops.get(1)
        assert op.form.status_id == 2
        assert op.form.priority_id == 9
        assert app.pending_ops.count == 1  # merged, not duplicated


class TestRowMarker:
    async def test_pending_row_shows_plus_marker(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        """A task with pending changes gets +N displayed in a dedicated column."""
        from textual.widgets import DataTable

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            # Queue a change on task 1
            await pilot.press('u')
            await pilot.pause()
            app.screen.form.status_id = 2
            app.screen.form.subject = 'X'  # 2 changed fields
            await pilot.press('g')
            await pilot.pause()
            # Back on MainScreen — inspect the table cell
            table = app.screen.query_one('#task-list', DataTable)
            # The queue column shows "+2" for task 1 (2 fields changed)
            cell = table.get_cell('1', 'queue')
            assert '2' in str(cell)


class TestInteractiveFilter:
    @pytest.fixture
    def filter_tasks(self) -> list[WorkPackage]:
        return [_wp(1, 'A'), _wp(2, 'B')]

    async def test_f_opens_filter_screen(
        self, filter_tasks: list[WorkPackage]
    ) -> None:
        from op.tui.filter_screen import FilterScreen

        cfg = Config(
            connection=ConnectionConfig(base_url='https://x'),
            defaults=DefaultsConfig(),
            remote=RemoteConfig(),
        )
        app = OpApp(tasks=filter_tasks, config=cfg)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('f')
            await pilot.pause()
            assert isinstance(app.screen, FilterScreen)

    async def test_apply_new_query_reloads_tasks_from_api(
        self, filter_tasks: list[WorkPackage]
    ) -> None:
        from op.search import SearchQuery
        from textual.widgets import DataTable

        reloaded: list[list[WorkPackage]] = []

        class ReloadClient:
            async def search_work_packages(
                self, *, filters=None, page_size=100,  # noqa: ANN001
            ):
                reloaded.append(filters or [])
                # Return a fresh task pretending the new filter matched it
                return [
                    WorkPackage(
                        id=42, subject='Fresh', type_id=1, type_name='Task',
                        status_id=1, status_name='Neu', project_id=10,
                        project_name='W', lock_version=1,
                    )
                ]

            async def update_work_package(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
                return None

        cfg = Config(
            connection=ConnectionConfig(base_url='https://x'),
            defaults=DefaultsConfig(),
            remote=RemoteConfig(),
        )
        app = OpApp(tasks=filter_tasks, config=cfg, client=ReloadClient())
        async with app.run_test() as pilot:
            await pilot.pause()
            # Directly trigger the reload via the public method
            new_query = SearchQuery(words=['fresh'])
            screen = app.screen
            await screen._reload_with_query(new_query)
            await pilot.pause()

            table = screen.query_one('#task-list', DataTable)
            assert table.row_count == 1
            assert app.current_query is new_query
            # API was called once and received a subject-contains filter
            assert len(reloaded) == 1


class TestProjectFilter:
    @pytest.fixture
    def mixed_tasks(self) -> list[WorkPackage]:
        return [
            _wp(1, 'Task A'),          # default project 10
            WorkPackage(
                id=2, subject='Task B', type_id=1, type_name='Task',
                status_id=1, status_name='Neu', project_id=20, project_name='Other',
                lock_version=1,
            ),
            _wp(3, 'Task C'),          # project 10
            WorkPackage(
                id=4, subject='Task D', type_id=1, type_name='Task',
                status_id=1, status_name='Neu', project_id=30, project_name='Third',
                lock_version=1,
            ),
        ]

    async def test_filter_hides_tasks_from_irrelevant_projects(
        self, mixed_tasks: list[WorkPackage]
    ) -> None:
        """Tasks whose project_id is in irrelevant_projects are omitted from the table."""
        from textual.widgets import DataTable

        cfg = Config(
            connection=ConnectionConfig(base_url='https://x'),
            defaults=DefaultsConfig(),
            remote=RemoteConfig(projects={10: 'P10', 20: 'P20', 30: 'P30'}),
        )
        cfg.filter.irrelevant_projects = [10]
        cfg.filter.project_filter_active = True
        app = OpApp(tasks=mixed_tasks, config=cfg)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one('#task-list', DataTable)
            # 4 total tasks; 2 from project 10 are hidden → 2 visible
            assert table.row_count == 2

    async def test_filter_inactive_shows_all(
        self, mixed_tasks: list[WorkPackage]
    ) -> None:
        from textual.widgets import DataTable

        cfg = Config(
            connection=ConnectionConfig(base_url='https://x'),
            defaults=DefaultsConfig(),
            remote=RemoteConfig(),
        )
        cfg.filter.irrelevant_projects = [10]
        cfg.filter.project_filter_active = False
        app = OpApp(tasks=mixed_tasks, config=cfg)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one('#task-list', DataTable)
            assert table.row_count == 4

    async def test_p_toggles_filter_state(
        self, mixed_tasks: list[WorkPackage], tmp_path
    ) -> None:
        from textual.widgets import DataTable

        cfg = Config(
            connection=ConnectionConfig(base_url='https://x'),
            defaults=DefaultsConfig(),
            remote=RemoteConfig(),
        )
        cfg.filter.irrelevant_projects = [10]
        cfg.filter.project_filter_active = False
        config_path = tmp_path / 'cfg.toml'
        config_path.write_text('[connection]\nbase_url = "x"\n')
        app = OpApp(
            tasks=mixed_tasks, config=cfg, config_path=config_path,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one('#task-list', DataTable)
            assert table.row_count == 4  # filter off
            await pilot.press('p')
            await pilot.pause()
            assert table.row_count == 2  # filter on
            await pilot.press('p')
            await pilot.pause()
            assert table.row_count == 4  # filter off again

    async def test_p_persists_filter_state_to_config(
        self, mixed_tasks: list[WorkPackage], tmp_path
    ) -> None:
        from op.config import load_config

        cfg = Config(
            connection=ConnectionConfig(base_url='https://x'),
            defaults=DefaultsConfig(),
            remote=RemoteConfig(),
        )
        cfg.filter.irrelevant_projects = [10]
        cfg.filter.project_filter_active = False
        config_path = tmp_path / 'cfg.toml'
        config_path.write_text('[connection]\nbase_url = "x"\n')
        app = OpApp(tasks=mixed_tasks, config=cfg, config_path=config_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('p')
            await pilot.pause()
        # Reload from disk, check persisted state
        reloaded = load_config(config_path)
        assert reloaded.filter.project_filter_active is True


class TestApplyAllBinding:
    async def test_g_notifies_when_queue_empty(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        """Pressing 'g' on the selector while queue is empty must not push a screen."""
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.pending_ops.count == 0
            await pilot.press('g')
            await pilot.pause()
            # Still on MainScreen
            from op.tui.main_screen import MainScreen
            assert isinstance(app.screen, MainScreen)


class TestOpenInBrowser:
    async def test_o_opens_current_task_in_browser(
        self, app_factory: T.Callable[..., OpApp], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        opened: list[str] = []
        monkeypatch.setattr('webbrowser.open', lambda url: opened.append(url))
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('o')
            await pilot.pause()
        assert opened == ['https://op.example.com/work_packages/1']

    async def test_o_follows_cursor(
        self, app_factory: T.Callable[..., OpApp], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        opened: list[str] = []
        monkeypatch.setattr('webbrowser.open', lambda url: opened.append(url))
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.press('down', 'down')
            await pilot.press('o')
            await pilot.pause()
        assert opened == ['https://op.example.com/work_packages/3']
