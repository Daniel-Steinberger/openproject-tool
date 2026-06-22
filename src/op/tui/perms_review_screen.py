"""Review screen for `op perms` — list planned membership additions before apply."""

from __future__ import annotations

from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header


class PermsReviewScreen(Screen[None]):
    BINDINGS = [
        Binding('d', 'delete', 'Entfernen', show=True),
        Binding('g', 'apply', 'Anwenden', show=True),
        Binding('q', 'back', 'Zurück', show=True),
        Binding('escape', 'back', 'Zurück', show=False),
    ]

    def compose(self):  # noqa: ANN201
        yield Header()
        yield DataTable(id='perms-review', cursor_type='row', zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.app.sub_title = 'Review geplanter Änderungen'
        table = self.query_one('#perms-review', DataTable)
        table.add_column('Geplante Änderung')
        self._populate()

    def _populate(self) -> None:
        table = self.query_one('#perms-review', DataTable)
        table.clear()
        for i, op in enumerate(self.app.perms_queue.all()):
            table.add_row(op.describe(self.app), key=str(i))
        if self.app.perms_queue.count == 0:
            self.app.pop_screen()

    def action_delete(self) -> None:
        table = self.query_one('#perms-review', DataTable)
        if table.cursor_row is None:
            return
        ops = self.app.perms_queue.all()
        if table.cursor_row >= len(ops):
            return
        self.app.perms_queue.remove(ops[table.cursor_row].key)
        self._populate()

    def action_apply(self) -> None:
        if self.app.perms_queue.count == 0:
            return
        from op.tui.perms_applying_screen import PermsApplyingScreen

        self.app.push_screen(PermsApplyingScreen())

    def action_back(self) -> None:
        self.app.pop_screen()
