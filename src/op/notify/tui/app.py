"""Root Textual app for `op notify`.

Separate from `OpApp` and `PermsApp`: no work-package state, no permission
state — just the analysed inbox and the queue of what to mark as read. The
analysis has already happened when this app starts; the TUI never talks to the
model, only to OpenProject.
"""

from __future__ import annotations

import typing as T

from textual.app import App
from textual.message import Message

from op.config import Config
from op.notify.analysis import GroupAnalysis
from op.notify.llm import LlmError
from op.notify.mark import MarkQueue
from op.notify.prompts import build_action_messages

_CLASSIFICATION_ORDER = {'relevant': 0, 'worth_knowing': 1, 'churn': 2}


class ActionLineReady(Message):
    """One work package's action line has arrived."""

    def __init__(self, work_package_id: int) -> None:
        super().__init__()
        self.work_package_id = work_package_id


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
    #notify-roles { padding: 0 1; height: auto; background: $panel; }
    #notify-action { padding: 0 1; height: auto; }
    #notify-applying-progress { dock: bottom; width: 100%; height: 1; }
    """

    def __init__(
        self,
        *,
        config: Config,
        client: T.Any,
        analyses: list[GroupAnalysis],
        llm: T.Any = None,
        own_user_id: int | None = None,
        user_name: str = '',
    ) -> None:
        super().__init__()
        self.config = config
        self.client = client
        self.analyses = sort_analyses(analyses)
        self.queue = MarkQueue()
        # Optional: the detail view asks it what a work package wants from the
        # user. None with --no-llm, and the view says so instead of pretending.
        self.llm = llm
        self.own_user_id = own_user_id
        self.user_name = user_name
        # Runtime only, one entry per work package: the answer does not change
        # while the program runs, and it costs a model call.
        self.action_lines: dict[int, str] = {}
        self._action_pending: set[int] = set()
        # Where the detail view last stood — the list cursor follows it back.
        self.detail_index: int | None = None

    def on_mount(self) -> None:
        from op.notify.tui.keybindings import apply_to_notify_screens
        from op.notify.tui.list_screen import NotifyListScreen

        apply_to_notify_screens(self.config)
        self.push_screen(NotifyListScreen())
        if self.llm is not None:
            # Top to bottom, in list order: what waits gets its line first.
            self.run_worker(self._fill_action_lines(), exclusive=False, group='action-lines')

    async def _fill_action_lines(self) -> None:
        for analysis in list(self.analyses):
            await self.fetch_action_line(analysis)

    async def fetch_action_line(self, analysis: GroupAnalysis) -> None:
        """Ask the model what this work package wants — at most once per run.

        Called both by the up-front pass and by the detail view, which may open a
        work package the pass has not reached yet; `_action_pending` keeps the two
        from asking twice.
        """
        work_package_id = analysis.work_package_id
        if work_package_id is None or self.llm is None:
            return
        if work_package_id in self.action_lines or work_package_id in self._action_pending:
            return
        self._action_pending.add(work_package_id)
        system, user = build_action_messages(
            block=analysis.block,
            user_name=self.user_name or 'the user',
            classification=analysis.classification,
            extra_instructions=self.config.notifications.extra_instructions,
        )
        try:
            answer = (await self.llm.complete_text(system=system, user=user)).strip()
        except LlmError as exc:
            answer = f'(nicht verfügbar: {exc})'
        finally:
            self._action_pending.discard(work_package_id)
        self.action_lines[work_package_id] = answer
        for screen in list(self.screen_stack):
            screen.post_message(ActionLineReady(work_package_id))

    def action_line(self, analysis: GroupAnalysis) -> str | None:
        """Finished line, or None while it is still being fetched / not asked for."""
        return self.action_lines.get(analysis.work_package_id or -1)

    @property
    def asks_the_model(self) -> bool:
        return self.llm is not None

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
