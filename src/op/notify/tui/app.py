"""Root Textual app for `op notify`.

Separate from `OpApp` and `PermsApp`: no work-package state, no permission
state — just the analysed inbox and the queue of what to mark as read. The
analysis has already happened when this app starts; the TUI never talks to the
model, only to OpenProject.
"""

from __future__ import annotations

import typing as T

from textual.app import App

from op.config import Config
from op.notify.analysis import GroupAnalysis
from op.notify.mark import MarkQueue

_CLASSIFICATION_ORDER = {'relevant': 0, 'worth_knowing': 1, 'churn': 2}


class NotifyApp(App[None]):
    TITLE = 'op notify'

    CSS = """
    Screen { layers: base overlay; }
    #notify-list, #notify-review, #notify-applying {
        height: 1fr;
        scrollbar-size-horizontal: 0;
        overflow-x: hidden;
    }
    #notify-detail { height: 1fr; padding: 0 1; }
    #notify-applying-progress { dock: bottom; width: 100%; height: 1; }
    """

    def __init__(
        self,
        *,
        config: Config,
        client: T.Any,
        analyses: list[GroupAnalysis],
    ) -> None:
        super().__init__()
        self.config = config
        self.client = client
        self.analyses = sort_analyses(analyses)
        self.queue = MarkQueue()
        # Where the detail view last stood — the list cursor follows it back.
        self.detail_index: int | None = None

    def on_mount(self) -> None:
        from op.notify.tui.keybindings import apply_to_notify_screens
        from op.notify.tui.list_screen import NotifyListScreen

        apply_to_notify_screens(self.config)
        self.push_screen(NotifyListScreen())

    def drop_marked(self, work_package_ids: list[int]) -> None:
        """Remove groups that were successfully marked — they are no longer unread."""
        done = set(work_package_ids)
        self.analyses = [a for a in self.analyses if a.work_package_id not in done]
        self.queue.clear()


def sort_analyses(analyses: list[GroupAnalysis]) -> list[GroupAnalysis]:
    """Relevant first, newest first inside a class — what waits gets read first."""
    return sorted(
        analyses,
        key=lambda a: (
            _CLASSIFICATION_ORDER.get(a.classification, 9),
            _invert(a.latest or ''),
        ),
    )


def _invert(value: str) -> tuple[int, str]:
    """Sort timestamps descending while the primary key stays ascending."""
    return (0, ''.join(chr(0x10FFFD - ord(c)) if ord(c) < 0x10FFFD else c for c in value))
