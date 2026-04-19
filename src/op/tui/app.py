from __future__ import annotations

from textual.app import App

from op.config import Config
from op.models import WorkPackage
from op.tui.main_screen import MainScreen


class OpApp(App[None]):
    """Root Textual app — hosts MainScreen plus any modals/sub-screens."""

    CSS = """
    Screen {
        layers: base overlay;
    }
    #task-list {
        height: 1fr;
    }
    """

    def __init__(self, *, tasks: list[WorkPackage], config: Config) -> None:
        super().__init__()
        self._initial_tasks = tasks
        self._config = config

    def on_mount(self) -> None:
        self.push_screen(MainScreen(tasks=self._initial_tasks, config=self._config))
