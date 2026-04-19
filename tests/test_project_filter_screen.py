from __future__ import annotations

import typing as T
from pathlib import Path

import pytest

from op.config import Config, ConnectionConfig, DefaultsConfig, RemoteConfig
from op.models import WorkPackage
from op.tui.app import OpApp
from op.tui.project_filter_screen import ProjectFilterScreen


def _wp(id: int) -> WorkPackage:
    return WorkPackage(
        id=id, subject='s', type_id=1, type_name='Task',
        status_id=1, status_name='Neu', project_id=10, project_name='W',
        lock_version=1,
    )


def _config_with_hierarchy() -> Config:
    """Root (1) → A (10) → A1 (11); Root B (2) → B1 (20)."""
    return Config(
        connection=ConnectionConfig(base_url='https://x'),
        defaults=DefaultsConfig(),
        remote=RemoteConfig(
            projects={1: 'Root A', 2: 'Root B', 10: 'A', 11: 'A1', 20: 'B1'},
            project_parents={10: 1, 11: 10, 20: 2},
        ),
    )


@pytest.fixture
def app_factory(tmp_path: Path) -> T.Callable[..., OpApp]:
    def _make(config: Config | None = None) -> OpApp:
        cfg = config or _config_with_hierarchy()
        config_path = tmp_path / 'cfg.toml'
        config_path.write_text('[connection]\nbase_url = "x"\n')
        return OpApp(tasks=[_wp(1)], config=cfg, config_path=config_path)

    return _make


class TestOpen:
    async def test_screen_mounts(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(ProjectFilterScreen(config=app._config))
            await pilot.pause()
            assert isinstance(app.screen, ProjectFilterScreen)


class TestHierarchy:
    async def test_projects_rendered_in_hierarchy_order(self, app_factory) -> None:  # noqa: ANN001
        """Children appear right after their parent, indented."""
        from textual.widgets import DataTable

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(ProjectFilterScreen(config=app._config))
            await pilot.pause()
            table = app.screen.query_one('#filter-table', DataTable)
            assert table.row_count == 5
            # Inspect name column — children are indented (depth * 2 spaces)
            names = [
                str(table.get_cell_at((r, 2)))
                for r in range(table.row_count)
            ]
            assert names[0].strip() == 'Root A'
            assert names[1].startswith('  ')  # A (depth 1)
            assert 'A' in names[1]
            assert names[2].startswith('    ')  # A1 (depth 2)
            assert 'A1' in names[2]


class TestToggle:
    async def test_space_toggles_current_project(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(ProjectFilterScreen(config=app._config))
            await pilot.pause()
            screen = app.screen
            await pilot.press('space')
            await pilot.pause()
            # The first row (Root A, id=1) should now be marked irrelevant
            assert 1 in screen.marked_ids


class TestSave:
    async def test_q_saves_irrelevant_list_to_config(self, app_factory) -> None:  # noqa: ANN001
        from op.config import load_config

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(ProjectFilterScreen(config=app._config))
            await pilot.pause()
            screen = app.screen
            screen.marked_ids.add(10)
            screen.marked_ids.add(11)
            await pilot.press('q')
            await pilot.pause()
        reloaded = load_config(app.config_path)
        assert set(reloaded.filter.irrelevant_projects) == {10, 11}

    async def test_escape_discards_changes(self, app_factory) -> None:  # noqa: ANN001
        from op.config import load_config

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(ProjectFilterScreen(config=app._config))
            await pilot.pause()
            app.screen.marked_ids.add(20)
            await pilot.press('escape')
            await pilot.pause()
        reloaded = load_config(app.config_path)
        assert reloaded.filter.irrelevant_projects == []


class TestCommandPalette:
    async def test_filter_command_registered(self, app_factory) -> None:  # noqa: ANN001
        """The Command-Palette provider must expose a 'Filter projects' entry."""
        from op.tui.project_filter_screen import ProjectFilterProvider

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            # The app must include our provider in its COMMANDS
            assert any(
                provider is ProjectFilterProvider or provider.__name__ == 'ProjectFilterProvider'
                for provider in app.COMMANDS
            )
