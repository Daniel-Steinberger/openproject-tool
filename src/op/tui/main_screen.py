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
_COL_ID = 'id'
_COL_STATUS = 'status'
_COL_TYPE = 'type'
_COL_SUBJECT = 'subject'


def _selection_mark(selected: bool) -> Text:
    """Return a visually distinct selection marker that survives cursor highlighting."""
    if selected:
        return Text('●', style='bold bright_green')
    return Text('○', style='dim')


class MainScreen(Screen[None]):
    """Aptitude-style task list: cursor navigation, space-to-select, i-invert, q-quit."""

    BINDINGS = [
        Binding('space', 'toggle_selected', 'Toggle', show=True),
        Binding('i', 'invert_selection', 'Invert', show=True),
        Binding('u', 'update', 'Update', show=True),
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
        table.add_column('ID', key=_COL_ID, width=10)
        table.add_column('Status', key=_COL_STATUS, width=16)
        table.add_column('Type', key=_COL_TYPE, width=10)
        table.add_column('Subject', key=_COL_SUBJECT)
        for task in self.tasks:
            table.add_row(
                _selection_mark(False),
                f'OP#{task.id}',
                task.status_name,
                task.type_name,
                task.subject,
                key=str(task.id),
            )
        table.focus()

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
        modal = UpdateModal(
            remote=self.config.remote,
            target_count=len(target_ids),
            wp=single_wp,
            client=self.client,
        )

        async def _apply(form: UpdateForm | None) -> None:
            if form is None:
                return
            if self.client is None:
                self.notify('No API client — changes not saved', severity='warning')
                return
            changes = form.api_changes()
            if not changes:
                self.notify('No changes to apply', severity='warning')
                return
            await self._apply_changes(list(target_ids), changes)

        self.app.push_screen(modal, _apply)

    async def _apply_changes(self, target_ids: list[int], changes: dict) -> None:
        """Send PATCH requests for each target task and report the result to the user."""
        updated = 0
        for task_id in target_ids:
            wp = self._tasks_by_id.get(task_id)
            if wp is None:
                continue
            try:
                fresh = await self.client.update_work_package(
                    task_id, lock_version=wp.lock_version, changes=changes
                )
            except Exception as exc:  # noqa: BLE001 — surface any API error to the user
                self.notify(
                    f'OP#{task_id} update failed: {exc}',
                    severity='error',
                    timeout=8,
                )
                continue
            updated += 1
            if fresh is not None:
                self._tasks_by_id[task_id] = fresh
                self._refresh_row(task_id, fresh)
        if updated:
            target = (
                f'OP#{target_ids[0]}' if updated == 1 else f'{updated} tasks'
            )
            self.notify(f'Updated {target}', severity='information')

    def _refresh_row(self, task_id: int, wp: WorkPackage) -> None:
        """Rewrite the Status / Type / Subject cells so the list reflects the server state."""
        table = self.query_one('#task-list', DataTable)
        try:
            table.update_cell(str(task_id), _COL_STATUS, wp.status_name)
            table.update_cell(str(task_id), _COL_TYPE, wp.type_name)
            table.update_cell(str(task_id), _COL_SUBJECT, wp.subject)
        except Exception:  # noqa: BLE001 — row may have been removed
            pass

    # --- internals -------------------------------------------------------

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
