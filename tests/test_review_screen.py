from __future__ import annotations

import typing as T

import pytest

from op.config import Config, ConnectionConfig, DefaultsConfig, RemoteConfig
from op.models import WorkPackage
from op.tui.app import AppState, OpApp
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
            statuses={1: 'Neu', 2: 'In Bearbeitung', 3: 'Erledigt'},
            types={1: 'Task', 2: 'Bug'},
            users={5: 'Max'},
            priorities={8: 'Normal'},
        ),
    )


@pytest.fixture
def tasks() -> list[WorkPackage]:
    return [_wp(1, 'Erstes'), _wp(2, 'Zweites'), _wp(3, 'Drittes')]


@pytest.fixture
def app_factory(tasks: list[WorkPackage]) -> T.Callable[..., OpApp]:
    def _make() -> OpApp:
        app = OpApp(tasks=tasks, config=_config())
        form = UpdateForm()
        form.status_id = 2
        app.pending_ops.add_or_merge(1, form, original_subject='Erstes')
        form2 = UpdateForm()
        form2.subject = 'Geänderter Titel'
        app.pending_ops.add_or_merge(2, form2, original_subject='Zweites')
        return app

    return _make


class TestOpen:
    async def test_g_on_selector_opens_review(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('g')
            await pilot.pause()
            assert isinstance(app.screen, ReviewScreen)
            assert AppState.REVIEW.value in app.sub_title

    async def test_q_returns_to_selector(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('g')
            await pilot.pause()
            await pilot.press('q')
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)


class TestContent:
    async def test_table_contains_all_pending_ops(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        from textual.widgets import DataTable

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('g')
            await pilot.pause()
            table = app.screen.query_one('#review-table', DataTable)
            assert table.row_count == 2


class TestDelete:
    async def test_d_removes_current_op(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('g')
            await pilot.pause()
            await pilot.press('d')
            await pilot.pause()
        assert app.pending_ops.count == 1

    async def test_d_when_queue_becomes_empty_returns_to_selector(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        """After removing the last pending op, the review screen is useless — go back."""
        app = app_factory()
        # Leave only one op
        app.pending_ops.remove(2)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('g')
            await pilot.pause()
            await pilot.press('d')
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)


class TestEdit:
    async def test_e_opens_modal_prefilled_with_current_form(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        from op.tui.update_modal import UpdateModal

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('g')
            await pilot.pause()
            await pilot.press('e')
            await pilot.pause()
            assert isinstance(app.screen, UpdateModal)
            # Task 1 has status_id=2 pre-queued
            assert app.screen.form.status_id == 2


class TestApplyBinding:
    async def test_g_triggers_apply_flow(
        self, app_factory: T.Callable[..., OpApp]
    ) -> None:
        """For now, g should at least not crash — ApplyingScreen arrives in Phase F."""
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('g')
            await pilot.pause()
            review = app.screen
            assert isinstance(review, ReviewScreen)
            await pilot.press('g')
            await pilot.pause()
            # Either transitioned or logged — just ensure no crash
            assert app.screen is not None
