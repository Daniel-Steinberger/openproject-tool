from __future__ import annotations

import typing as T
from enum import Enum
from pathlib import Path

from textual.app import App

from op.config import Config
from op.models import WorkPackage
from op.queue import OperationQueue
from op.tui.main_screen import MainScreen


class AppState(str, Enum):
    SELECTOR = 'Task Selector'
    DETAIL = 'Task Detail'
    REVIEW = 'Change Review'
    APPLYING = 'Change Application'


class OpApp(App[None]):
    """Root Textual app — hosts the main-state screens and the shared change queue."""

    TITLE = 'OpApp'

    CSS = """
    Screen {
        layers: base overlay;
    }
    #task-list {
        height: 1fr;
        scrollbar-size-horizontal: 0;
        overflow-x: hidden;
    }
    #review-table {
        scrollbar-size-horizontal: 0;
        overflow-x: hidden;
    }
    #applying-table {
        scrollbar-size-horizontal: 0;
        overflow-x: hidden;
    }
    """

    def __init__(
        self,
        *,
        tasks: list[WorkPackage],
        config: Config,
        client: T.Any | None = None,
        config_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._initial_tasks = tasks
        self._config = config
        self._client = client
        self.config_path: Path | None = config_path
        self.pending_ops: OperationQueue = OperationQueue()

    def on_mount(self) -> None:
        self.push_screen(
            MainScreen(tasks=self._initial_tasks, config=self._config, client=self._client)
        )
        self.set_state(AppState.SELECTOR)

    def set_state(self, state: AppState, *, detail: str | None = None) -> None:
        """Update the window sub-title to reflect the current state + pending count."""
        parts = [state.value]
        if detail:
            parts.append(f'· {detail}')
        count = self.pending_ops.count
        if count:
            parts.append(f'({count} pending)')
        self.sub_title = ' '.join(parts)
