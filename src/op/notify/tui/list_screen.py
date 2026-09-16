"""Inbox list: one row per work package, what waits for you at the top."""

from __future__ import annotations

import webbrowser

from rich.text import Text
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from op.notify.analysis import GroupAnalysis
from op.notify.tui.app import ActionLineReady

_MARK_COLUMN = 'mark'
_CLASSIFICATION_STYLE = {
    'relevant': ('relevant', 'bold red'),
    'worth_knowing': ('zur Kenntnis', 'yellow'),
    'churn': ('Rauschen', 'dim'),
}


class NotifyListScreen(Screen[None]):
    BINDINGS = [
        Binding('space', 'toggle_selected', 'Markieren', show=True),
        Binding('i', 'invert_selection', 'Invertieren', show=True),
        Binding('c', 'select_churn', 'Rauschen', show=True),
        Binding('a', 'select_all', 'Alle', show=True),
        Binding('g', 'review', 'Review', show=True),
        Binding('o', 'open_browser', 'Browser', show=True),
        Binding('q', 'quit', 'Beenden', show=True),
    ]

    def compose(self):  # noqa: ANN201
        yield Header()
        yield DataTable(id='notify-list', cursor_type='row', zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one('#notify-list', DataTable)
        table.add_column('', key=_MARK_COLUMN, width=2)
        table.add_column('WP', width=7)
        table.add_column('Einstufung', width=13)
        table.add_column('Titel', width=34)
        table.add_column('Anz.', width=5)
        table.add_column('Was zu tun ist')
        self.populate()

    def on_screen_resume(self) -> None:
        # Coming back from review/applying: what was marked is gone by then.
        # Coming back from the detail view: follow wherever n/p ended up.
        index = self.app.detail_index
        self.app.detail_index = None
        self.populate()
        if index is not None:
            table = self.query_one('#notify-list', DataTable)
            if table.row_count:
                table.move_cursor(row=min(index, table.row_count - 1))

    def populate(self) -> None:
        table = self.query_one('#notify-list', DataTable)
        cursor = table.cursor_row
        table.clear()
        for analysis in self.app.analyses:
            table.add_row(*self._row(analysis), key=self._key(analysis))
        self._update_subtitle()
        if cursor:
            table.move_cursor(row=min(cursor, max(table.row_count - 1, 0)))

    def _row(self, analysis: GroupAnalysis) -> tuple[Text, ...]:
        label, style = _CLASSIFICATION_STYLE.get(
            analysis.classification, (analysis.classification, '')
        )
        if analysis.error:
            label, style = 'Fehler', 'red'
        marked = self.app.queue.contains(analysis.work_package_id)
        waits = '✓' if analysis.waits_for_me else ''
        return (
            Text('✓' if marked else '', style='bold green'),
            Text(f'#{analysis.work_package_id}' if analysis.work_package_id else '—'),
            Text(label, style=style),
            Text(f'{analysis.title}  {waits}'.rstrip(), overflow='ellipsis', no_wrap=True),
            Text(str(analysis.count)),
            self._action_cell(analysis),
        )

    def _action_cell(self, analysis: GroupAnalysis) -> Text:
        line = self.app.action_line(analysis)
        if line:
            return Text(line, overflow='ellipsis', no_wrap=True)
        if self.app.asks_the_model:
            return Text('…', style='dim')
        return Text('')

    @staticmethod
    def _key(analysis: GroupAnalysis) -> str:
        return str(analysis.work_package_id or f'other-{analysis.notification_ids}')

    def _update_subtitle(self) -> None:
        total = len(self.app.analyses)
        waiting = sum(1 for a in self.app.analyses if a.waits_for_me)
        self.app.sub_title = (
            f'{total} Work Package(s) · {waiting} warten auf dich · '
            f'{self.app.queue.count} markiert'
        )

    # --- actions ---------------------------------------------------------

    def current(self) -> GroupAnalysis | None:
        table = self.query_one('#notify-list', DataTable)
        if table.cursor_row is None or table.cursor_row >= len(self.app.analyses):
            return None
        return self.app.analyses[table.cursor_row]

    def action_toggle_selected(self) -> None:
        analysis = self.current()
        if analysis is None:
            return
        if self.app.queue.contains(analysis.work_package_id):
            self.app.queue.remove(analysis.work_package_id)
        else:
            self.app.queue.add(analysis)
        self.populate()

    def action_invert_selection(self) -> None:
        selected = {a.work_package_id for a in self.app.queue.all()}
        self.app.queue.clear()
        for analysis in self.app.analyses:
            if analysis.work_package_id not in selected:
                self.app.queue.add(analysis)
        self.populate()

    def action_select_churn(self) -> None:
        self.app.queue.clear()
        for analysis in self.app.analyses:
            if analysis.is_churn:
                self.app.queue.add(analysis)
        self.populate()

    def action_select_all(self) -> None:
        self.app.queue.clear()
        for analysis in self.app.analyses:
            self.app.queue.add(analysis)
        self.populate()

    def action_review(self) -> None:
        from op.notify.tui.review_screen import NotifyReviewScreen

        if self.app.queue.count:
            self.app.push_screen(NotifyReviewScreen())

    def action_quit(self) -> None:
        # A screen binding does not reach App.action_quit in Textual 8 — the
        # action is looked up on the screen, so it has to live here.
        self.app.exit()

    def action_open_browser(self) -> None:
        analysis = self.current()
        if analysis is None or analysis.work_package_id is None:
            return
        base = self.app.config.connection.base_url.rstrip('/')
        webbrowser.open(f'{base}/work_packages/{analysis.work_package_id}')

    def on_action_line_ready(self, _: ActionLineReady) -> None:
        # Repaint as the lines trickle in, keeping cursor and selection.
        self.populate()

    def on_data_table_row_selected(self, _: DataTable.RowSelected) -> None:
        from op.notify.tui.detail_screen import NotifyDetailScreen

        table = self.query_one('#notify-list', DataTable)
        if table.cursor_row is None or table.cursor_row >= len(self.app.analyses):
            return
        self.app.push_screen(NotifyDetailScreen(table.cursor_row))
