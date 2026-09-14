"""Review before marking: exactly what will be marked as read."""

from __future__ import annotations

from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header


class NotifyReviewScreen(Screen[None]):
    BINDINGS = [
        Binding('d', 'delete', 'Entfernen', show=True),
        Binding('g', 'apply', 'Als gelesen markieren', show=True),
        Binding('q', 'back', 'Zurück', show=True),
        Binding('escape', 'back', 'Zurück', show=False),
    ]

    def compose(self):  # noqa: ANN201
        yield Header()
        yield DataTable(id='notify-review', cursor_type='row', zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one('#notify-review', DataTable)
        table.add_column('WP', width=7)
        table.add_column('Titel')
        table.add_column('Einstufung', width=13)
        table.add_column('Anz.', width=5)
        self._populate()

    def on_screen_resume(self) -> None:
        self._populate()

    def _populate(self) -> None:
        table = self.query_one('#notify-review', DataTable)
        table.clear()
        entries = self.app.queue.all()
        for analysis in entries:
            table.add_row(
                f'#{analysis.work_package_id}', analysis.title, analysis.classification,
                str(len(analysis.notification_ids)),
            )
        count = len(self.app.queue.notification_ids)
        self.app.sub_title = f'{count} Benachrichtigung(en) in {len(entries)} Work Package(s)'
        if not entries:
            self.app.pop_screen()

    def action_delete(self) -> None:
        table = self.query_one('#notify-review', DataTable)
        entries = self.app.queue.all()
        if table.cursor_row is None or table.cursor_row >= len(entries):
            return
        self.app.queue.remove(entries[table.cursor_row].work_package_id)
        self._populate()

    def action_apply(self) -> None:
        from op.notify.tui.applying_screen import NotifyApplyingScreen

        if self.app.queue.count:
            self.app.push_screen(NotifyApplyingScreen())

    def action_back(self) -> None:
        self.app.pop_screen()
