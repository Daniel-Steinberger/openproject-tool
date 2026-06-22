"""Review screen for `op perms` — list planned membership additions before apply."""

from __future__ import annotations

from rich.text import Text
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
        self.app.sub_title = 'Review geplanter Berechtigungen'
        table = self.query_one('#perms-review', DataTable)
        table.add_column('Projekt')
        table.add_column('Principal')
        table.add_column('Rollen', width=24)
        self._populate()

    def _populate(self) -> None:
        table = self.query_one('#perms-review', DataTable)
        table.clear()
        for op in self.app.perms_queue.all():
            table.add_row(
                self.app.projects.get(op.project_id, str(op.project_id)),
                self._principal_label(op),
                self.app.role_label(sorted(op.role_ids)),
                key=f'{op.project_id}:{op.kind}:{op.principal_id}',
            )
        if self.app.perms_queue.count == 0:
            self.app.pop_screen()

    def _principal_label(self, op) -> Text:  # noqa: ANN001
        label = self.app.principal_label(op.kind, op.principal_id)
        prefix = '▸ ' if op.kind == 'group' else ''
        return Text(f'{prefix}{label}', style='bold' if op.kind == 'group' else '')

    def action_delete(self) -> None:
        table = self.query_one('#perms-review', DataTable)
        if table.cursor_row is None:
            return
        ops = self.app.perms_queue.all()
        if table.cursor_row >= len(ops):
            return
        op = ops[table.cursor_row]
        self.app.perms_queue.remove(op.key)
        self._populate()

    def action_apply(self) -> None:
        if self.app.perms_queue.count == 0:
            return
        from op.tui.perms_applying_screen import PermsApplyingScreen

        self.app.push_screen(PermsApplyingScreen())

    def action_back(self) -> None:
        self.app.pop_screen()
