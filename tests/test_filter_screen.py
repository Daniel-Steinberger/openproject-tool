from __future__ import annotations

import typing as T
from pathlib import Path

import pytest

from op.config import Config, ConnectionConfig, DefaultsConfig, RemoteConfig
from op.models import WorkPackage
from op.search import SearchQuery
from op.tui.app import OpApp
from op.tui.filter_screen import FilterScreen


def _wp(id: int) -> WorkPackage:
    return WorkPackage(
        id=id, subject='s', type_id=1, type_name='Task',
        status_id=1, status_name='Neu', project_id=10, project_name='W',
        lock_version=1,
    )


def _config() -> Config:
    return Config(
        connection=ConnectionConfig(base_url='https://x'),
        defaults=DefaultsConfig(),
        remote=RemoteConfig(),
    )


@pytest.fixture
def app_factory(tmp_path: Path) -> T.Callable[..., OpApp]:
    def _make(query: SearchQuery | None = None) -> OpApp:
        config_path = tmp_path / 'cfg.toml'
        config_path.write_text('[connection]\nbase_url = "x"\n')
        app = OpApp(tasks=[_wp(1)], config=_config(), config_path=config_path)
        if query is not None:
            app.current_query = query
        return app

    return _make


class TestMount:
    async def test_mounts_with_prefilled_inputs(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        from textual.widgets import Input

        initial = SearchQuery(
            words=['deploy'],
            filters={'status': ['open'], 'type': ['Task', 'Bug']},
        )
        app = app_factory(initial)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(FilterScreen(query=app.current_query))
            await pilot.pause()
            assert isinstance(app.screen, FilterScreen)
            assert app.screen.query_one('#input-words', Input).value == 'deploy'
            assert app.screen.query_one('#input-status', Input).value == 'open'
            assert app.screen.query_one('#input-type', Input).value == 'Task, Bug'


class TestApply:
    async def test_g_builds_query_from_inputs(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        from textual.widgets import Input

        app = app_factory()
        results: list[SearchQuery | None] = []
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(FilterScreen(query=SearchQuery()), lambda q: results.append(q))
            await pilot.pause()
            screen = app.screen
            screen.query_one('#input-words', Input).value = 'deploy bug'
            screen.query_one('#input-status', Input).value = 'open'
            screen.query_one('#input-type', Input).value = 'Task, Bug'
            await pilot.press('g')
            await pilot.pause()

        assert len(results) == 1
        query = results[0]
        assert query is not None
        assert query.words == ['deploy', 'bug']
        assert query.filters == {
            'status': ['open'],
            'type': ['Task', 'Bug'],
        }

    async def test_q_discards(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        results: list[SearchQuery | None] = []
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(FilterScreen(query=SearchQuery()), lambda q: results.append(q))
            await pilot.pause()
            await pilot.press('q')
            await pilot.pause()

        assert results == [None]

    async def test_empty_inputs_yield_empty_query(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        results: list[SearchQuery | None] = []
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(FilterScreen(query=SearchQuery()), lambda q: results.append(q))
            await pilot.pause()
            await pilot.press('g')
            await pilot.pause()

        assert results == [SearchQuery()]
