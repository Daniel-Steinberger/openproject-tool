from __future__ import annotations

import logging
import typing as T
import webbrowser

from rich.text import Text
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

log = logging.getLogger(__name__)

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
    total += len(form.add_watcher_ids) + len(form.remove_watcher_ids)
    return total


class MainScreen(Screen[None]):
    """Task selector: cursor navigation, space-to-select, u-edit-to-queue, g-review-queue."""

    BINDINGS = [
        Binding('space', 'toggle_selected', 'Toggle', show=True),
        Binding('i', 'invert_selection', 'Invert', show=True),
        Binding('u', 'update', 'Edit', show=True),
        Binding('g', 'review_queue', 'Apply', show=True),
        Binding('f', 'open_filter', 'Filter', show=True),
        Binding('o', 'open_browser', 'Open', show=True),
        Binding('p', 'toggle_project_filter', 'Proj-Filter', show=True),
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
        self.all_tasks = tasks          # full, unfiltered list
        self.tasks = self._apply_filter(tasks, config)
        self.config = config
        self.client = client
        self.selection = Selection()
        self._tasks_by_id = {t.id: t for t in self.tasks}

    @staticmethod
    def _apply_filter(tasks, config):  # noqa: ANN001, ANN205
        """Return tasks visible under the current project-filter configuration."""
        if not config.filter.project_filter_active:
            return list(tasks)
        irrelevant = set(config.filter.irrelevant_projects)
        return [t for t in tasks if t.project_id not in irrelevant]

    def compose(self):  # noqa: ANN201
        yield Header()
        yield DataTable(id='task-list', cursor_type='row', zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        log.info(
            'MainScreen.on_mount client=%s tasks=%d',
            type(self.client).__name__ if self.client is not None else 'None',
            len(self.tasks),
        )
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

    def action_open_filter(self) -> None:
        """Open the runtime filter editor; on apply, reload tasks from the API."""
        from op.search import SearchQuery
        from op.tui.filter_screen import FilterScreen

        current = getattr(self.app, 'current_query', None) or SearchQuery()

        def _on_dismiss(new_query):  # noqa: ANN001, ANN202
            if new_query is None:
                return
            self.run_worker(self._reload_with_query(new_query), exclusive=True)

        self.app.push_screen(FilterScreen(query=current), _on_dismiss)

    async def _reload_with_query(self, query) -> None:  # noqa: ANN001
        """Replace the task list via a fresh API call using the new query."""
        from op.search import build_api_filters

        if self.client is None:
            self.notify('No API client — cannot reload', severity='warning')
            return
        try:
            if query.task_id is not None:
                wp = await self.client.get_work_package(query.task_id)
                new_tasks = [wp] if wp is not None else []
            else:
                api_filters = build_api_filters(query, self.config.remote)
                new_tasks = await self.client.search_work_packages(filters=api_filters)
        except Exception as exc:  # noqa: BLE001
            log.exception('Filter reload failed')
            self.notify(f'Filter failed: {exc}', severity='error', timeout=8)
            return
        self.app.current_query = query
        self.all_tasks = list(new_tasks)
        self.tasks = self._apply_filter(self.all_tasks, self.config)
        self._tasks_by_id = {t.id: t for t in self.tasks}
        self.selection = Selection()
        self._rebuild_rows()
        self._update_state_label()
        self.notify(f'Loaded {len(self.tasks)} task(s)', severity='information')

    def action_toggle_project_filter(self) -> None:
        """Toggle the project filter on/off and persist the new state."""
        from op.config import update_filter

        new_state = not self.config.filter.project_filter_active
        self.config.filter.project_filter_active = new_state
        self.tasks = self._apply_filter(self.all_tasks, self.config)
        self._tasks_by_id = {t.id: t for t in self.tasks}
        # Drop selection markers for rows that no longer exist
        self.selection = Selection()
        self._rebuild_rows()
        # Persist to config file
        path = getattr(self.app, 'config_path', None)
        if path is not None:
            try:
                update_filter(path, project_filter_active=new_state)
            except Exception:  # noqa: BLE001
                log.exception('Failed to persist project filter state')
        self._update_state_label()

    def _rebuild_rows(self) -> None:
        table = self.query_one('#task-list', DataTable)
        table.clear()
        for task in self.tasks:
            pending = self._queue().get(task.id)
            count = _count_changed_fields(pending.form) if pending else 0
            table.add_row(
                _selection_mark(False),
                _queue_mark(count),
                f'OP#{task.id}',
                task.status_name,
                task.type_name,
                task.subject,
                key=str(task.id),
            )

    def action_review_queue(self) -> None:
        """Open the review screen — or notify if the queue is empty."""
        if self._queue().count == 0:
            self.notify('No pending changes', severity='warning')
            return
        log.info(
            'MainScreen.action_review_queue pushing ReviewScreen client=%s',
            type(self.client).__name__ if self.client is not None else 'None',
        )
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

    def refresh_row(self, wp: WorkPackage) -> None:
        """Public: apply fresh server state to the row (called from ApplyingScreen)."""
        self._tasks_by_id[wp.id] = wp
        table = self.query_one('#task-list', DataTable)
        try:
            table.update_cell(str(wp.id), _COL_STATUS, wp.status_name)
            table.update_cell(str(wp.id), _COL_TYPE, wp.type_name)
            table.update_cell(str(wp.id), _COL_SUBJECT, wp.subject)
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
