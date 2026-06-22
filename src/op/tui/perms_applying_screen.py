"""Applying screen for `op perms` — executes queued membership changes (additive).

For each (project, principal): if the principal is already a member, add the
missing roles via PATCH; otherwise create the membership. Mirrors the
status/progress model of tui/applying_screen.py.
"""

from __future__ import annotations

import logging

from rich.text import Text
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, ProgressBar, RichLog

log = logging.getLogger(__name__)

_COL_STATUS = 'status'
_COL_TEXT = 'text'

_STATUS_MARK = {
    'pending': Text('·', style='dim'),
    'running': Text('⟳', style='bold yellow'),
    'done':    Text('✓', style='bold green'),
    'failed':  Text('✗', style='bold red'),
}


class PermsApplyingScreen(Screen[None]):
    BINDINGS = [Binding('q', 'close', 'Close', show=True)]

    def __init__(self) -> None:
        super().__init__()
        self.is_done = False
        self._has_failures = False

    def compose(self):  # noqa: ANN201
        yield Header()
        yield DataTable(id='perms-applying', cursor_type='row', zebra_stripes=True)
        yield RichLog(id='perms-applying-errors', wrap=True, highlight=False, markup=True)
        yield ProgressBar(id='perms-applying-progress', show_eta=False)
        yield Footer()

    def on_mount(self) -> None:
        self.app.sub_title = 'Anwenden…'
        table = self.query_one('#perms-applying', DataTable)
        table.add_column('', key=_COL_STATUS, width=3)
        table.add_column('Änderung', key=_COL_TEXT)
        ops = self.app.perms_queue.all()
        if not ops:
            self._return_to_root()
            return
        for op in ops:
            table.add_row(_STATUS_MARK['pending'], self._describe(op), key=self._key(op))
        self.query_one('#perms-applying-progress', ProgressBar).update(
            total=len(ops), progress=0
        )
        self.run_worker(self._run(), exclusive=True)

    def _key(self, op) -> str:  # noqa: ANN001
        return f'{op.project_id}:{op.kind}:{op.principal_id}'

    def _describe(self, op) -> str:  # noqa: ANN001
        proj = self.app.projects.get(op.project_id, str(op.project_id))
        who = self.app.principal_label(op.kind, op.principal_id)
        return f'{proj}: + {who} [{self.app.role_label(sorted(op.role_ids))}]'

    async def _run(self) -> None:
        ops = self.app.perms_queue.all()
        table = self.query_one('#perms-applying', DataTable)
        progress = self.query_one('#perms-applying-progress', ProgressBar)
        for index, op in enumerate(ops):
            op.status = 'running'
            table.update_cell(self._key(op), _COL_STATUS, _STATUS_MARK['running'])
            ok = await self._apply_single(op)
            mark = 'done' if ok else 'failed'
            op.status = mark
            if not ok:
                self._has_failures = True
                self._log_error(op)
            table.update_cell(self._key(op), _COL_STATUS, _STATUS_MARK[mark])
            progress.update(progress=index + 1)
        self.is_done = True
        self.app.perms_queue.clear_done()
        self.app.loaded = False  # force reload so the tree reflects the new state
        if not self._has_failures:
            self._return_to_root()

    async def _apply_single(self, op) -> bool:  # noqa: ANN001
        existing = self._existing_membership(op)
        try:
            if existing is None:
                await self.app.client.create_membership(
                    op.project_id, op.principal_id, sorted(op.role_ids),
                    principal_type=op.kind,
                )
            else:
                union = set(existing.role_ids) | op.role_ids
                if union != set(existing.role_ids):
                    await self.app.client.update_membership_roles(
                        existing.id, sorted(union)
                    )
        except Exception as exc:  # noqa: BLE001
            op.error = str(exc) or exc.__class__.__name__
            log.exception('perms apply failed for %s: %s', self._key(op), exc)
            return False
        return True

    def _existing_membership(self, op):  # noqa: ANN001, ANN202
        for m in self.app.memberships.get(op.project_id, []):
            if m.principal_type == op.kind and m.principal_id == op.principal_id:
                return m
        return None

    def _log_error(self, op) -> None:  # noqa: ANN001
        widget = self.query_one('#perms-applying-errors', RichLog)
        if 'visible' not in widget.classes:
            widget.add_class('visible')
        widget.write(f'[red]{self._describe(op)} — {op.error}[/red]')

    def action_close(self) -> None:
        if not self.is_done:
            return
        if self._has_failures:
            self.app.pop_screen()
        else:
            self._return_to_root()

    def _return_to_root(self) -> None:
        from op.tui.perms_projects_screen import PermsProjectsScreen

        while not isinstance(self.app.screen, PermsProjectsScreen):
            if len(self.app.screen_stack) <= 1:
                break
            self.app.pop_screen()
