"""Execute the marking, one notification at a time, with progress and failures."""

from __future__ import annotations

import logging

from rich.text import Text
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, ProgressBar, RichLog

log = logging.getLogger('op.notify.tui.applying')

_COL_STATUS = 'status'
_STATUS_MARK = {
    'pending': Text('·', style='dim'),
    'done': Text('✓', style='bold green'),
    'failed': Text('✗', style='bold red'),
}


class NotifyApplyingScreen(Screen[None]):
    BINDINGS = [Binding('q', 'close', 'Schließen', show=True)]

    def __init__(self) -> None:
        super().__init__()
        self.is_done = False

    def compose(self):  # noqa: ANN201
        yield Header()
        yield DataTable(id='notify-applying', cursor_type='row', zebra_stripes=True)
        yield RichLog(id='notify-applying-errors', wrap=True, highlight=False, markup=True)
        yield ProgressBar(id='notify-applying-progress', show_eta=False)
        yield Footer()

    def on_mount(self) -> None:
        self.app.sub_title = 'Markiere als gelesen…'
        table = self.query_one('#notify-applying', DataTable)
        table.add_column('', key=_COL_STATUS, width=3)
        table.add_column('Work Package')
        entries = self.app.queue.all()
        if not entries:
            self.app.pop_screen()
            return
        for analysis in entries:
            table.add_row(
                _STATUS_MARK['pending'],
                f'#{analysis.work_package_id} — {analysis.title}',
                key=str(analysis.work_package_id),
            )
        self.query_one('#notify-applying-progress', ProgressBar).update(
            total=len(self.app.queue.notification_ids), progress=0
        )
        self.run_worker(self._run(), exclusive=True)

    async def _run(self) -> None:
        queue = self.app.queue
        marked_ids = [a.work_package_id for a in queue.all()]
        progress = self.query_one('#notify-applying-progress', ProgressBar)

        result = await queue.apply(
            self.app.client,
            on_progress=lambda done, total: progress.update(total=total, progress=done),
        )

        table = self.query_one('#notify-applying', DataTable)
        failed_ids = {nid for nid, _ in result.failed}
        for analysis in list(queue.all()):
            status = 'failed' if failed_ids & set(analysis.notification_ids) else 'done'
            table.update_cell(str(analysis.work_package_id), _COL_STATUS, _STATUS_MARK[status])

        if result.failed:
            errors = self.query_one('#notify-applying-errors', RichLog)
            for notification_id, message in result.failed:
                errors.write(f'[red]#{notification_id}:[/red] {message}')
            # Groups that failed stay in the list — they are still unread.
            marked_ids = [
                a.work_package_id for a in queue.all()
                if not (failed_ids & set(a.notification_ids))
            ]

        self.app.sub_title = (
            f'{result.marked} markiert' + (f', {len(result.failed)} fehlgeschlagen'
                                           if result.failed else '')
        )
        self.app.drop_marked([i for i in marked_ids if i is not None])
        self.is_done = True

    def action_close(self) -> None:
        # The screens below refresh themselves on resume; an empty review screen
        # pops itself, so this lands back on the list.
        self.app.pop_screen()
