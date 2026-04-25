"""Ignore-list screen — view and manage individually ignored tasks.

Reachable via the command palette (Ctrl+P → "Ignored tasks"). The screen shows
all task IDs currently on the ignore list (with subjects when known). Tasks can
be removed individually; the ignore filter can be toggled here as well.
"""

from __future__ import annotations

import logging
import typing as T
from functools import partial

from rich.text import Text
from textual.app import App
from textual.binding import Binding
from textual.command import Hit, Hits, Provider
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from op.config import Config, update_filter

log = logging.getLogger(__name__)

_COL_CHECK = 'check'
_COL_ID = 'id'
_COL_SUBJECT = 'subject'


def _filter_badge(active: bool) -> str:
    return '[filter ON]' if active else '[filter OFF]'


class IgnoreListScreen(Screen[None]):
    """List of ignored tasks; space to unignore, f to toggle filter, q to close."""

    BINDINGS = [
        Binding('space', 'unignore', 'Unignore', show=True),
        Binding('f', 'toggle_filter', 'Filter on/off', show=True),
        Binding('q', 'close', 'Close', show=True),
        Binding('escape', 'close', 'Close', show=False),
    ]

    def __init__(self, *, config: Config, task_subjects: dict[int, str]) -> None:
        super().__init__()
        self.config = config
        self.task_subjects = task_subjects

    def compose(self) -> T.Any:
        yield Header()
        yield DataTable(id='ignore-table', cursor_type='row', zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        from op.tui.app import AppState

        self.app.set_state(AppState.SELECTOR, detail=self._detail_label())
        table = self.query_one('#ignore-table', DataTable)
        table.add_column('', key=_COL_CHECK, width=3)
        table.add_column('ID', key=_COL_ID, width=10)
        table.add_column('Subject', key=_COL_SUBJECT)
        for tid in self.config.filter.ignored_tasks:
            table.add_row(
                Text('●', style='bold bright_red'),
                f'OP#{tid}',
                self.task_subjects.get(tid, '—'),
                key=str(tid),
            )
        table.focus()

    # --- actions ---------------------------------------------------------

    def action_unignore(self) -> None:
        task_id = self._current_task_id()
        if task_id is None:
            return
        ignored = list(self.config.filter.ignored_tasks)
        if task_id in ignored:
            ignored.remove(task_id)
            self.config.filter.ignored_tasks = ignored
            self._persist()
        table = self.query_one('#ignore-table', DataTable)
        try:
            table.remove_row(str(task_id))
        except Exception:  # noqa: BLE001
            pass
        self._update_title()

    def action_toggle_filter(self) -> None:
        new_state = not self.config.filter.ignore_filter_active
        self.config.filter.ignore_filter_active = new_state
        self._persist(ignore_filter_active=new_state)
        self._update_title()

    def action_close(self) -> None:
        self.app.pop_screen()

    # --- internals -------------------------------------------------------

    def _persist(self, *, ignore_filter_active: bool | None = None) -> None:
        path = getattr(self.app, 'config_path', None)
        if path is None:
            return
        try:
            update_filter(
                path,
                ignored_tasks=self.config.filter.ignored_tasks,
                ignore_filter_active=ignore_filter_active,
            )
        except Exception:  # noqa: BLE001
            log.exception('Failed to persist ignore list')

    def _detail_label(self) -> str:
        count = len(self.config.filter.ignored_tasks)
        badge = _filter_badge(self.config.filter.ignore_filter_active)
        return f'Ignored Tasks ({count}) {badge}'

    def _update_title(self) -> None:
        from op.tui.app import AppState

        self.app.set_state(AppState.SELECTOR, detail=self._detail_label())

    def _current_task_id(self) -> int | None:
        table = self.query_one('#ignore-table', DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key.value is None:
            return None
        return int(row_key.value)


class IgnoreListProvider(Provider):
    """Command-palette provider exposing the Ignore-list screen."""

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        label = 'Ignored tasks'
        score = matcher.match(label)
        if score > 0:
            yield Hit(
                score,
                matcher.highlight(label),
                partial(_open_ignore_list_screen, self.app),
                help='View and manage the list of individually ignored tasks',
            )


def _open_ignore_list_screen(app: App) -> None:
    config: Config = app._config  # type: ignore[attr-defined]
    task_subjects: dict[int, str] = getattr(app, 'task_subjects', {})
    app.push_screen(IgnoreListScreen(config=config, task_subjects=task_subjects))
