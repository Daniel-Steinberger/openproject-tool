"""Review screen — list of pending operations with edit/delete/apply controls."""

from __future__ import annotations

import typing as T

from rich.text import Text
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from op.config import Config
from op.queue import PendingOperation
from op.tui.update_form import UpdateForm
from op.tui.update_modal import UpdateModal

_COL_ID = 'id'
_COL_SUBJECT = 'subject'
_COL_CHANGES = 'changes'


class ReviewScreen(Screen[None]):
    """Main screen listing all pending operations before they are applied."""

    BINDINGS = [
        Binding('e', 'edit', 'Edit', show=True),
        Binding('d', 'delete', 'Delete', show=True),
        Binding('g', 'apply_all', 'Apply', show=True),
        Binding('q', 'back', 'Back', show=True),
    ]

    def __init__(self, *, config: Config, client: T.Any | None = None) -> None:
        super().__init__()
        self.config = config
        self.client = client

    def compose(self):  # noqa: ANN201
        yield Header()
        yield DataTable(id='review-table', cursor_type='row', zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        from op.tui.app import AppState

        self.app.set_state(AppState.REVIEW)
        table = self.query_one('#review-table', DataTable)
        table.add_column('ID', key=_COL_ID, width=10)
        table.add_column('Subject', key=_COL_SUBJECT, width=40)
        table.add_column('Changes', key=_COL_CHANGES)
        self._populate_rows()
        table.focus()

    # --- actions ---------------------------------------------------------

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_delete(self) -> None:
        task_id = self._current_task_id()
        if task_id is None:
            return
        self.app.pending_ops.remove(task_id)
        if self.app.pending_ops.count == 0:
            self.app.pop_screen()
            return
        self._populate_rows()
        self._refresh_state_label()

    def action_edit(self) -> None:
        task_id = self._current_task_id()
        if task_id is None:
            return
        op = self.app.pending_ops.get(task_id)
        if op is None:
            return
        modal = UpdateModal(
            remote=self.config.remote,
            target_count=1,
            wp=None,
            client=self.client,
        )
        modal.form.merge_from(op.form)

        def _on_dismiss(form: UpdateForm | None) -> None:
            if form is None:
                return
            if not form.has_changes:
                # User cleared everything — treat as delete
                self.app.pending_ops.remove(task_id)
            else:
                fresh = UpdateForm()
                fresh.merge_from(form)
                # Overwrite (not merge) so the user can actually remove fields
                self.app.pending_ops.remove(task_id)
                self.app.pending_ops.add_or_merge(task_id, fresh)
            self._populate_rows()
            self._refresh_state_label()
            if self.app.pending_ops.count == 0:
                self.app.pop_screen()

        self.app.push_screen(modal, _on_dismiss)

    def action_apply_all(self) -> None:
        """Apply all pending ops — opens the ApplyingScreen (added in Phase F).

        For now this is a no-op placeholder so the binding exists.
        """
        self.notify(
            f'Applying {self.app.pending_ops.count} change(s) — runner coming soon'
        )

    # --- internals -------------------------------------------------------

    def _populate_rows(self) -> None:
        table = self.query_one('#review-table', DataTable)
        table.clear()
        remote = self.config.remote
        users_and_groups = {**remote.users, **remote.groups}
        for op in self.app.pending_ops.all():
            table.add_row(
                f'OP#{op.task_id}',
                op.original_subject or '',
                Text(
                    op.summary(
                        statuses=remote.statuses,
                        types=remote.types,
                        priorities=remote.priorities,
                        users=users_and_groups,
                    ),
                    style='yellow',
                ),
                key=str(op.task_id),
            )

    def _current_task_id(self) -> int | None:
        table = self.query_one('#review-table', DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key.value is None:
            return None
        return int(row_key.value)

    def _refresh_state_label(self) -> None:
        from op.tui.app import AppState

        self.app.set_state(AppState.REVIEW)


__all__ = ['ReviewScreen', 'PendingOperation']
