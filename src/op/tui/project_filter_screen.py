"""Project filter screen — user picks projects to treat as irrelevant.

Reachable via the command palette (Ctrl+P → "Filter projects"). The picked
project IDs are persisted to config.filter.irrelevant_projects; the actual
filter-on/off toggle is handled separately by the MainScreen via the `p` key.
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
_COL_NAME = 'name'


def _build_hierarchy(
    projects: dict[int, str], parents: dict[int, int]
) -> list[tuple[int, int, str]]:
    """Return [(project_id, depth, name)] in parent-before-child order."""
    children: dict[int | None, list[int]] = {}
    for pid in projects:
        parent = parents.get(pid)
        children.setdefault(parent, []).append(pid)
    # Stable order by project name
    for group in children.values():
        group.sort(key=lambda pid: projects[pid].lower())

    result: list[tuple[int, int, str]] = []

    def _walk(parent: int | None, depth: int) -> None:
        for pid in children.get(parent, []):
            result.append((pid, depth, projects[pid]))
            _walk(pid, depth + 1)

    # Roots: parents that don't exist in projects, plus explicit None
    all_parent_keys = set(children.keys())
    roots: set[int | None] = {None}
    for parent in all_parent_keys:
        if parent is None or parent not in projects:
            roots.add(parent)
    for root in sorted(roots, key=lambda k: (k is None, k or 0)):
        _walk(root, 0)
    return result


class ProjectFilterScreen(Screen[None]):
    """Checkbox list of all known projects; space marks as irrelevant, q saves."""

    BINDINGS = [
        Binding('space', 'toggle', 'Toggle', show=True),
        Binding('i', 'invert', 'Invert', show=True),
        Binding('q', 'save_close', 'Save', show=True),
        Binding('enter', 'save_close', 'Save', show=False),
        Binding('escape', 'discard_close', 'Cancel', show=True),
    ]

    def __init__(self, *, config: Config) -> None:
        super().__init__()
        self.config = config
        self.marked_ids: set[int] = set(config.filter.irrelevant_projects)

    def compose(self):  # noqa: ANN201
        yield Header()
        yield DataTable(id='filter-table', cursor_type='row', zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        from op.tui.app import AppState

        self.app.set_state(AppState.SELECTOR, detail='Project Filter')
        table = self.query_one('#filter-table', DataTable)
        table.add_column('', key=_COL_CHECK, width=3)
        table.add_column('ID', key=_COL_ID, width=8)
        table.add_column('Project', key=_COL_NAME)
        remote = self.config.remote
        self._rows = _build_hierarchy(remote.projects, remote.project_parents)
        for pid, depth, name in self._rows:
            table.add_row(
                self._mark(pid),
                f'#{pid}',
                '  ' * depth + name,
                key=str(pid),
            )
        table.focus()

    # --- actions ---------------------------------------------------------

    def action_toggle(self) -> None:
        pid = self._current_project_id()
        if pid is None:
            return
        if pid in self.marked_ids:
            self.marked_ids.discard(pid)
        else:
            self.marked_ids.add(pid)
        self._refresh_row(pid)

    def action_invert(self) -> None:
        all_ids = {pid for pid, _, _ in self._rows}
        self.marked_ids = all_ids - self.marked_ids
        for pid, _, _ in self._rows:
            self._refresh_row(pid)

    def action_save_close(self) -> None:
        self._persist()
        self.app.pop_screen()

    def action_discard_close(self) -> None:
        self.app.pop_screen()

    # --- internals -------------------------------------------------------

    def _persist(self) -> None:
        self.config.filter.irrelevant_projects = sorted(self.marked_ids)
        path = getattr(self.app, 'config_path', None)
        if path is None:
            return
        try:
            update_filter(path, irrelevant_projects=sorted(self.marked_ids))
        except Exception:  # noqa: BLE001
            log.exception('Failed to persist irrelevant_projects')

    def _mark(self, pid: int) -> Text:
        return (
            Text('●', style='bold bright_green')
            if pid in self.marked_ids
            else Text('○', style='dim')
        )

    def _current_project_id(self) -> int | None:
        table = self.query_one('#filter-table', DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key.value is None:
            return None
        return int(row_key.value)

    def _refresh_row(self, pid: int) -> None:
        table = self.query_one('#filter-table', DataTable)
        try:
            table.update_cell(str(pid), _COL_CHECK, self._mark(pid))
        except Exception:  # noqa: BLE001
            pass


class ProjectFilterProvider(Provider):
    """Command-palette provider exposing the Filter-Projects screen."""

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        label = 'Filter projects'
        score = matcher.match(label)
        if score > 0:
            yield Hit(
                score,
                matcher.highlight(label),
                partial(_open_filter_screen, self.app),
                help='Configure which projects to hide from the task list',
            )


def _open_filter_screen(app: App) -> None:
    config: Config = app._config  # type: ignore[attr-defined]
    app.push_screen(ProjectFilterScreen(config=config))
