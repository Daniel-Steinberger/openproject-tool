"""Project tree for `op perms` — shows hierarchy with permission-mismatch flags."""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Header, Label

from op.perms import build_hierarchy, has_mismatch, plan_propagation, plan_transfer

_COL_FLAG = 'flag'
_COL_ID = 'id'
_COL_NAME = 'name'

_FLAG_MISMATCH = Text('▲', style='bold yellow')
_FLAG_OK = Text(' ')


class PermsProjectsScreen(Screen[None]):
    """Hierarchical project list. `▲` marks a project whose source set differs
    from its parent's (additive view)."""

    BINDINGS = [
        Binding('c', 'copy', 'Von Projekt übertragen', show=True),
        Binding('f', 'fix', 'Hierarchie angleichen', show=True),
        Binding('g', 'review', 'Review/Apply', show=True),
        Binding('r', 'reload', 'Neu laden', show=True),
        Binding('q', 'quit_app', 'Quit', show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[tuple[int, int, str]] = []

    def compose(self):  # noqa: ANN201
        yield Header()
        yield Label('Lade Berechtigungen…', id='perms-loading')
        yield DataTable(id='perms-projects', cursor_type='row', zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one('#perms-projects', DataTable)
        table.add_column('', key=_COL_FLAG, width=3)
        table.add_column('ID', key=_COL_ID, width=8)
        table.add_column('Projekt', key=_COL_NAME)
        self.run_worker(self._load_and_populate(), exclusive=True)

    async def _load_and_populate(self) -> None:
        await self.app.load_data()
        self.query_one('#perms-loading', Label).display = False
        self._populate()
        self._update_subtitle()

    def _populate(self) -> None:
        table = self.query_one('#perms-projects', DataTable)
        table.clear()
        self._rows = build_hierarchy(self.app.projects, self.app.parents)
        for pid, depth, name in self._rows:
            table.add_row(
                self._flag_for(pid),
                str(pid),
                '  ' * depth + name,
                key=str(pid),
            )
        if self.app.start_project is not None:
            self._move_cursor_to(self.app.start_project)

    def _flag_for(self, pid: int) -> Text:
        parent = self.app.parents.get(pid)
        if parent is None or parent not in self.app.projects:
            return _FLAG_OK
        if has_mismatch(self.app.source_set(parent), self.app.source_set(pid)):
            return _FLAG_MISMATCH
        return _FLAG_OK

    def _move_cursor_to(self, pid: int) -> None:
        for i, (rid, _, _) in enumerate(self._rows):
            if rid == pid:
                self.query_one('#perms-projects', DataTable).move_cursor(row=i)
                return

    def _current_project(self) -> int | None:
        table = self.query_one('#perms-projects', DataTable)
        if table.cursor_row is None or not self._rows:
            return None
        return self._rows[table.cursor_row][0]

    def _update_subtitle(self) -> None:
        n = self.app.perms_queue.count
        self.app.sub_title = f'{n} geplante Änderung(en)' if n else 'Berechtigungen'

    # --- actions ---------------------------------------------------------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        from op.tui.perms_detail_screen import PermsDetailScreen

        self.app.push_screen(PermsDetailScreen(int(event.row_key.value)))

    def action_fix(self) -> None:
        pid = self._current_project()
        if pid is None:
            return
        plans = plan_propagation(pid, self.app.parents, self.app.source_sets)
        if not plans:
            self.notify('Teilbaum ist bereits konsistent.', timeout=4)
            return
        self.app.perms_queue.add_many(plans)
        self._update_subtitle()
        self.notify(
            f'{len(plans)} Angleichung(en) eingeplant für den Teilbaum von '
            f'{self.app.projects.get(pid, pid)}. "g" zum Review.',
            timeout=6,
        )

    def action_copy(self) -> None:
        dst = self._current_project()
        if dst is None:
            return

        def _on_pick(src: int | None) -> None:
            if src is None or src == dst:
                return
            plans = plan_transfer(
                self.app.source_set(src), self.app.source_set(dst), dst
            )
            if not plans:
                self.notify('Ziel hat bereits alle Quell-Berechtigungen.', timeout=4)
                return
            self.app.perms_queue.add_many(plans)
            self._update_subtitle()
            self.notify(
                f'{len(plans)} Übertragung(en) von {self.app.projects.get(src, src)} '
                f'→ {self.app.projects.get(dst, dst)} eingeplant. "g" zum Review.',
                timeout=6,
            )

        self.app.push_screen(
            PermsProjectPickerScreen(self._rows, title='Quell-Projekt wählen'), _on_pick
        )

    def action_review(self) -> None:
        if self.app.perms_queue.count == 0:
            self.notify('Keine geplanten Änderungen.', timeout=3)
            return
        from op.tui.perms_review_screen import PermsReviewScreen

        self.app.push_screen(PermsReviewScreen())

    def action_reload(self) -> None:
        self.app.loaded = False
        self.app.memberships.clear()
        self.app.group_members.clear()
        self.app.source_sets.clear()
        self.query_one('#perms-loading', Label).display = True
        self.run_worker(self._load_and_populate(), exclusive=True)

    def action_quit_app(self) -> None:
        self.app.exit()

    def on_screen_resume(self) -> None:
        if self.app.loaded:
            self._populate()
            self._update_subtitle()


class PermsProjectPickerScreen(ModalScreen[int | None]):
    """Modal hierarchical project picker; returns the chosen project id."""

    BINDINGS = [
        Binding('enter', 'pick', 'Wählen', show=True),
        Binding('escape', 'cancel', 'Abbrechen', show=True),
    ]

    DEFAULT_CSS = """
    PermsProjectPickerScreen { align: center middle; }
    PermsProjectPickerScreen > Vertical {
        background: $panel; border: round $accent; padding: 0 1;
        width: 70; height: auto; max-height: 80%;
    }
    PermsProjectPickerScreen DataTable { height: auto; max-height: 24; }
    """

    def __init__(self, rows: list[tuple[int, int, str]], *, title: str) -> None:
        super().__init__()
        self._rows = rows
        self._title = title

    def compose(self):  # noqa: ANN201
        from textual.containers import Vertical

        with Vertical():
            yield Label(self._title)
            yield DataTable(id='perms-picker', cursor_type='row', zebra_stripes=True)
            yield Footer()

    def on_mount(self) -> None:
        table = self.query_one('#perms-picker', DataTable)
        table.add_column('ID', width=8)
        table.add_column('Projekt')
        for pid, depth, name in self._rows:
            table.add_row(str(pid), '  ' * depth + name, key=str(pid))
        table.focus()

    def action_pick(self) -> None:
        table = self.query_one('#perms-picker', DataTable)
        if table.cursor_row is None or not self._rows:
            self.dismiss(None)
            return
        self.dismiss(self._rows[table.cursor_row][0])

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.dismiss(int(event.row_key.value))

    def action_cancel(self) -> None:
        self.dismiss(None)
