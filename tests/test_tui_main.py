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
