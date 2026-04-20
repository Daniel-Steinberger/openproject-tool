from __future__ import annotations

from op.config import Config, ConnectionConfig, DefaultsConfig, RemoteConfig
from op.models import WorkPackage
from op.tui.app import AppState, OpApp


def _wp(id: int) -> WorkPackage:
    return WorkPackage(
        id=id, subject='s', type_id=1, type_name='Task',
        status_id=1, status_name='Neu', project_id=10, project_name='W',
        lock_version=1,
    )


def _config() -> Config:
    return Config(
        connection=ConnectionConfig(base_url='https://op.example.com'),
        defaults=DefaultsConfig(),
        remote=RemoteConfig(),
    )


class TestSharedQueue:
    def test_app_has_pending_ops_queue(self) -> None:
        app = OpApp(tasks=[_wp(1)], config=_config())
        assert app.pending_ops is not None
        assert app.pending_ops.count == 0


class TestCurrentQuery:
    def test_default_empty_query(self) -> None:
        app = OpApp(tasks=[_wp(1)], config=_config())
        assert app.current_query is not None
        assert app.current_query.words == []
        assert app.current_query.filters == {}

    def test_initial_query_preserved(self) -> None:
        from op.search import SearchQuery

        q = SearchQuery(words=['foo'], filters={'status': ['open']})
        app = OpApp(tasks=[_wp(1)], config=_config(), query=q)
        assert app.current_query is q


class TestSubTitle:
    async def test_selector_sub_title(self) -> None:
        app = OpApp(tasks=[_wp(1)], config=_config())
        async with app.run_test() as pilot:
            await pilot.pause()
            assert 'Task Selector' in app.sub_title

    async def test_sub_title_shows_pending_count(self) -> None:
        from op.tui.update_form import UpdateForm

        app = OpApp(tasks=[_wp(1)], config=_config())
        async with app.run_test() as pilot:
            await pilot.pause()
            form = UpdateForm()
            form.status_id = 2
            app.pending_ops.add_or_merge(1, form)
            app.set_state(AppState.SELECTOR)
            assert '1 pending' in app.sub_title

    async def test_sub_title_without_pending_has_no_count(self) -> None:
        app = OpApp(tasks=[_wp(1)], config=_config())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.set_state(AppState.SELECTOR)
            assert 'pending' not in app.sub_title


class TestAppStateEnum:
    def test_labels(self) -> None:
        assert AppState.SELECTOR.value == 'Task Selector'
        assert AppState.REVIEW.value == 'Change Review'
        assert AppState.APPLYING.value == 'Change Application'
        assert AppState.DETAIL.value == 'Task Detail'
