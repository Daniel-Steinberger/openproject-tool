from __future__ import annotations

import typing as T
import webbrowser

from rich.text import Text
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from op.config import Config
from op.models import WorkPackage
from op.tui.detail_screen import DetailScreen
from op.tui.selection import Selection
from op.tui.update_form import UpdateForm
from op.tui.update_modal import UpdateModal

_COL_SEL = 'sel'
_COL_QUEUE = 'queue'
_COL_ID = 'id'
_COL_STATUS = 'status'
_COL_TYPE = 'type'
_COL_SUBJECT = 'subject'


def _selection_mark(selected: bool) -> Text:
    """Return a visually distinct selection marker that survives cursor highlighting."""
    if selected:
        return Text('●', style='bold bright_green')
    return Text('○', style='dim')


def _queue_mark(count: int) -> Text:
    if count == 0:
        return Text('')
    return Text(f'+{count}', style='bold yellow')


def _count_changed_fields(form: UpdateForm) -> int:
    changes = form.api_changes()
    total = 0
    if '_links' in changes:
        total += len(changes['_links'])
    total += sum(1 for k in changes if k != '_links')
    return total


class MainScreen(Screen[None]):
    """Task selector: cursor navigation, space-to-select, u-edit-to-queue, g-review-queue."""

    BINDINGS = [
        Binding('space', 'toggle_selected', 'Toggle', show=True),
        Binding('i', 'invert_selection', 'Invert', show=True),
        Binding('u', 'update', 'Edit', show=True),
        Binding('g', 'review_queue', 'Apply', show=True),
        Binding('o', 'open_browser', 'Open', show=True),
        Binding('q', 'quit', 'Quit', show=True),
    ]

    def __init__(
        self,
        *,
        tasks: list[WorkPackage],
        config: Config,
        client: T.Any | None = None,
    ) -> None:
        super().__init__()
        self.tasks = tasks
        self.config = config
        self.client = client
        self.selection = Selection()
        self._tasks_by_id = {t.id: t for t in tasks}

    def compose(self):  # noqa: ANN201
        yield Header()
        yield DataTable(id='task-list', cursor_type='row', zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one('#task-list', DataTable)
        table.add_column('', key=_COL_SEL, width=3)
        table.add_column('', key=_COL_QUEUE, width=3)
        table.add_column('ID', key=_COL_ID, width=10)
        table.add_column('Status', key=_COL_STATUS, width=16)
        table.add_column('Type', key=_COL_TYPE, width=10)
        table.add_column('Subject', key=_COL_SUBJECT)
        for task in self.tasks:
            table.add_row(
                _selection_mark(False),
                _queue_mark(0),
                f'OP#{task.id}',
                task.status_name,
                task.type_name,
                task.subject,
                key=str(task.id),
            )
        table.focus()
        self._update_state_label()

    def on_screen_resume(self) -> None:
        """Re-populate queue markers + state label when returning from a sub-screen."""
        for task in self.tasks:
            self._refresh_queue_cell(task.id)
        self._update_state_label()

    # --- actions ---------------------------------------------------------

    def action_toggle_selected(self) -> None:
        task_id = self._current_task_id()
        if task_id is None:
            return
        self.selection.toggle(task_id)
        self._refresh_mark(task_id)

    def action_invert_selection(self) -> None:
        self.selection.invert(all_ids=[t.id for t in self.tasks])
        for task in self.tasks:
            self._refresh_mark(task.id)

    def action_quit(self) -> None:
        self.app.exit()

    def action_open_browser(self) -> None:
        task_id = self._current_task_id()
        if task_id is None:
            return
        base_url = self.config.connection.base_url.rstrip('/')
        webbrowser.open(f'{base_url}/work_packages/{task_id}')

    def action_review_queue(self) -> None:
        """Open the review screen — or notify if the queue is empty."""
        if self._queue().count == 0:
            self.notify('No pending changes', severity='warning')
            return
        from op.tui.review_screen import ReviewScreen

        self.app.push_screen(
            ReviewScreen(config=self.config, client=self.client)
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value is None:
            return
        task_id = int(event.row_key.value)
        wp = self._tasks_by_id.get(task_id)
        if wp is None:
            return
        self.app.push_screen(DetailScreen(wp=wp, config=self.config, client=self.client))

    def action_update(self) -> None:
        target_ids = self._target_ids()
        if not target_ids:
            return
        single_wp = self._tasks_by_id.get(target_ids[0]) if len(target_ids) == 1 else None
        # Pre-fill with any pending form already queued for this (single) task
        modal = UpdateModal(
            remote=self.config.remote,
            target_count=len(target_ids),
            wp=single_wp,
            client=self.client,
        )
        if single_wp is not None:
            pending = self._queue().get(single_wp.id)
            if pending is not None:
                modal.form.merge_from(pending.form)

        def _on_dismiss(form: UpdateForm | None) -> None:
            if form is None or not form.has_changes:
                return
            for task_id in target_ids:
                wp = self._tasks_by_id.get(task_id)
                self._queue().add_or_merge(
                    task_id,
                    _clone_form(form),
                    original_subject=wp.subject if wp else None,
                )
                self._refresh_queue_cell(task_id)
            self._update_state_label()

        self.app.push_screen(modal, _on_dismiss)

    # --- internals -------------------------------------------------------

    def _queue(self):  # noqa: ANN202
        return self.app.pending_ops

    def _update_state_label(self) -> None:
        """Ask the app to re-render the sub-title with the current pending count."""
        from op.tui.app import AppState

        self.app.set_state(AppState.SELECTOR)

    def _refresh_queue_cell(self, task_id: int) -> None:
        pending = self._queue().get(task_id)
        count = _count_changed_fields(pending.form) if pending else 0
        table = self.query_one('#task-list', DataTable)
        try:
            table.update_cell(str(task_id), _COL_QUEUE, _queue_mark(count))
        except Exception:  # noqa: BLE001
            pass

    def _target_ids(self) -> list[int]:
        selected = self.selection.as_list()
        if selected:
            return selected
        current = self._current_task_id()
        return [current] if current is not None else []

    def _current_task_id(self) -> int | None:
        table = self.query_one('#task-list', DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key.value is None:
            return None
        return int(row_key.value)

    def _refresh_mark(self, task_id: int) -> None:
        marker = _selection_mark(self.selection.contains(task_id))
        table = self.query_one('#task-list', DataTable)
        table.update_cell(str(task_id), _COL_SEL, marker)


def _clone_form(form: UpdateForm) -> UpdateForm:
    """Return a fresh form with all fields of `form` merged in — avoids sharing state."""
    clone = UpdateForm()
    clone.merge_from(form)
    return clone
