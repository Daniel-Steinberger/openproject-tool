"""Applying screen — executes queued operations sequentially with live progress."""

from __future__ import annotations

import logging
import typing as T

log = logging.getLogger(__name__)

from rich.text import Text
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, ProgressBar, RichLog

from op.config import Config

_COL_STATUS = 'status'
_COL_ID = 'id'
_COL_CHANGES = 'changes'

_STATUS_MARK = {
    'pending': Text('·', style='dim'),
    'running': Text('⟳', style='bold yellow'),
    'done':    Text('✓', style='bold green'),
    'failed':  Text('✗', style='bold red'),
}


class ApplyingScreen(Screen[None]):
    """Runs the queued PendingOperations one by one, updating their status in place."""

    BINDINGS = [
        Binding('q', 'close', 'Close', show=True),
    ]

    DEFAULT_CSS = """
    ApplyingScreen #applying-table {
        height: 1fr;
    }
    ApplyingScreen #applying-errors {
        height: auto;
        max-height: 10;
        border-top: solid $error;
        background: $panel;
        padding: 0 1;
        display: none;
    }
    ApplyingScreen #applying-errors.visible {
        display: block;
    }
    ApplyingScreen #applying-progress {
        dock: bottom;
        width: 100%;
        height: 1;
    }
    """

    def __init__(self, *, config: Config, client: T.Any | None = None) -> None:
        super().__init__()
        self.config = config
        self.client = client
        self.is_done = False
        self._has_failures = False

    def compose(self):  # noqa: ANN201
        yield Header()
        yield DataTable(id='applying-table', cursor_type='row', zebra_stripes=True)
        yield RichLog(id='applying-errors', wrap=True, highlight=False, markup=True)
        yield ProgressBar(id='applying-progress', show_eta=False)
        yield Footer()

    def on_mount(self) -> None:
        from op.tui.app import AppState

        self.app.set_state(AppState.APPLYING)
        table = self.query_one('#applying-table', DataTable)
        table.add_column('', key=_COL_STATUS, width=3)
        table.add_column('ID', key=_COL_ID, width=10)
        table.add_column('Changes', key=_COL_CHANGES)
        ops = self.app.pending_ops.all()
        if not ops:
            # Nothing to do — bounce back to selector (which is two screens below
            # for the normal Selector → Review → Applying path, but we may also
            # land here directly from an empty queue).
            self._return_to_selector()
            return
        for op in ops:
            table.add_row(
                _STATUS_MARK['pending'],
                f'OP#{op.task_id}',
                self._changes_summary(op),
                key=str(op.task_id),
            )
        self.query_one('#applying-progress', ProgressBar).update(
            total=len(ops), progress=0
        )
        self.run_worker(self._run(), exclusive=True)

    # --- actions ---------------------------------------------------------

    def action_close(self) -> None:
        """Close the screen. Only takes effect once all operations have finished."""
        if not self.is_done:
            return
        # Failures: pop back to Review; Success: pop back to Selector
        if self._has_failures:
            self.app.pop_screen()
        else:
            self._return_to_selector()

    # --- execution -------------------------------------------------------

    async def _run(self) -> None:
        ops = self.app.pending_ops.all()
        table = self.query_one('#applying-table', DataTable)
        progress = self.query_one('#applying-progress', ProgressBar)

        for index, op in enumerate(ops):
            op.status = 'running'
            table.update_cell(str(op.task_id), _COL_STATUS, _STATUS_MARK['running'])

            ok = await self._apply_single(op)
            if ok:
                op.status = 'done'
                table.update_cell(str(op.task_id), _COL_STATUS, _STATUS_MARK['done'])
            else:
                op.status = 'failed'
                self._has_failures = True
                table.update_cell(str(op.task_id), _COL_STATUS, _STATUS_MARK['failed'])
                self._log_error(op)

            progress.update(progress=index + 1)

        self.is_done = True
        # Remove successfully-applied ops; failed ones stay so the user can fix+retry.
        self.app.pending_ops.clear_done()
        if not self._has_failures:
            self._return_to_selector()

    async def _apply_single(self, op) -> bool:  # noqa: ANN001
        if self.client is None:
            op.error = 'internal error: ApplyingScreen has no client reference'
            log.error(
                'OP#%s apply aborted — self.client is None. ReviewScreen.client type=%s',
                op.task_id,
                type(self.app.screen_stack[-2]).__name__
                if len(self.app.screen_stack) > 1 else 'n/a',
            )
            return False
        main_screen = self._find_main_screen()
        wp = main_screen._tasks_by_id.get(op.task_id) if main_screen else None
        lock_version = wp.lock_version if wp is not None else 1

        if op.form.has_patch_changes:
            try:
                fresh = await self.client.update_work_package(
                    op.task_id, lock_version=lock_version, changes=op.form.api_changes()
                )
            except Exception as exc:  # noqa: BLE001
                op.error = str(exc) or exc.__class__.__name__
                log.exception(
                    'OP#%s update failed (lock=%s): %s',
                    op.task_id, lock_version, exc,
                )
                return False
            log.info('OP#%s updated', op.task_id)
            if fresh is not None and main_screen is not None:
                main_screen.refresh_row(fresh)

        if op.form.has_watcher_changes:
            try:
                for uid in op.form.add_watcher_ids:
                    await self.client.add_watcher(op.task_id, uid)
                for uid in op.form.remove_watcher_ids:
                    await self.client.remove_watcher(op.task_id, uid)
            except Exception as exc:  # noqa: BLE001
                op.error = str(exc) or exc.__class__.__name__
                log.exception('OP#%s watcher update failed: %s', op.task_id, exc)
                return False

        return True

    def _log_error(self, op) -> None:  # noqa: ANN001
        """Append a failure line to the error log and reveal it."""
        log = self.query_one('#applying-errors', RichLog)
        if 'visible' not in log.classes:
            log.add_class('visible')
        log.write(f'[bold red]OP#{op.task_id}[/bold red] [red]{op.error}[/red]')

    def _find_main_screen(self):  # noqa: ANN202
        from op.tui.main_screen import MainScreen

        for screen in self.app.screen_stack:
            if isinstance(screen, MainScreen):
                return screen
        return None

    # --- helpers ---------------------------------------------------------

    def _changes_summary(self, op) -> Text:  # noqa: ANN001
        remote = self.config.remote
        text = op.summary(
            statuses=remote.statuses,
            types=remote.types,
            priorities=remote.priorities,
            projects=remote.projects,
            users={**remote.users, **remote.groups},
        )
        return Text(text or '(no changes)', style='yellow')

    def _return_to_selector(self) -> None:
        """Pop ourselves plus any ReviewScreen above us until we reach the main screen."""
        from op.tui.main_screen import MainScreen

        while not isinstance(self.app.screen, MainScreen):
            if len(self.app.screen_stack) <= 1:
                break
            self.app.pop_screen()
