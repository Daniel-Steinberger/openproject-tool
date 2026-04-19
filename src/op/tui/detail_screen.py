from __future__ import annotations

import typing as T
import webbrowser

from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, Markdown, Static

from op.config import Config
from op.models import Activity, WorkPackage
from op.tui.comment_modal import CommentModal
from op.tui.update_form import UpdateForm
from op.tui.update_modal import UpdateModal


class DetailScreen(Screen[None]):
    """Full task detail: metadata, description, activity log + inline edit/comment."""

    BINDINGS = [
        Binding('q', 'close', 'Back', show=True),
        Binding('escape', 'close', 'Back', show=False),
        Binding('e', 'edit', 'Edit', show=True),
        Binding('c', 'comment', 'Comment', show=True),
        Binding('o', 'open_browser', 'Open', show=True),
    ]

    DEFAULT_CSS = """
    DetailScreen #meta {
        background: $boost;
        padding: 1 2;
    }
    DetailScreen #description {
        padding: 0 2;
        margin-bottom: 1;
    }
    DetailScreen #activity-header {
        text-style: bold;
        padding: 0 2;
    }
    DetailScreen .activity {
        padding: 0 2;
    }
    """

    def __init__(
        self,
        *,
        wp: WorkPackage,
        config: Config,
        client: T.Any | None = None,
    ) -> None:
        super().__init__()
        self.wp = wp
        self.config = config
        self.client = client
        self._activities: list[Activity] = []

    def compose(self):  # noqa: ANN201
        yield Header()
        with VerticalScroll():
            yield Label(self._meta_text(), id='meta')
            if self.wp.description:
                yield Markdown(self.wp.description, id='description')
            yield Label('Activity', id='activity-header')
            yield Static(id='activity-list')
        yield Footer()

    def on_mount(self) -> None:
        from op.tui.app import AppState

        self.app.set_state(AppState.DETAIL, detail=f'OP#{self.wp.id}')
        if self.client is not None:
            self.run_worker(self._load_activities(), exclusive=True)

    async def _load_activities(self) -> None:
        try:
            self._activities = await self.client.get_activities(self.wp.id)
        except Exception:  # noqa: BLE001 — TUI must stay alive even if API blips
            self._activities = []
        self._render_activities()

    def _render_activities(self) -> None:
        widget = self.query_one('#activity-list', Static)
        if not self._activities:
            widget.update('[dim](no comments)[/dim]')
            return
        lines = []
        for activity in self._activities:
            if not activity.comment:
                continue
            user = activity.user_name or '(unknown)'
            when = activity.created_at or ''
            lines.append(f'[bold]{user}[/bold]  [dim]{when}[/dim]\n{activity.comment}\n')
        widget.update('\n'.join(lines) if lines else '[dim](no comments)[/dim]')

    def _meta_text(
        self,
        *,
        statuses_lookup: dict[int, str] | None = None,
        types_lookup: dict[int, str] | None = None,
        priorities_lookup: dict[int, str] | None = None,
        users_lookup: dict[int, str] | None = None,
    ) -> str:
        """Build the meta header with overlaid pending-diff annotations."""
        remote = self.config.remote
        statuses = statuses_lookup if statuses_lookup is not None else remote.statuses
        types = types_lookup if types_lookup is not None else remote.types
        priorities = priorities_lookup if priorities_lookup is not None else remote.priorities
        users = users_lookup if users_lookup is not None else {**remote.users, **remote.groups}

        pending = self._pending_form()
        subject = self._diff_text(
            self.wp.subject, pending.subject if pending else None
        )

        parts = [
            f'[bold cyan]OP#{self.wp.id}[/bold cyan]  [bold]{subject}[/bold]',
            self._status_type_project_line(pending, statuses, types),
        ]
        priority_line = self._priority_line(pending, priorities)
        if priority_line:
            parts.append(priority_line)
        assignee_line = self._assignee_line(pending, users)
        if assignee_line:
            parts.append(assignee_line)
        start_due_line = self._start_due_line(pending)
        if start_due_line:
            parts.append(start_due_line)
        return '\n'.join(parts)

    def _pending_form(self):  # noqa: ANN202
        try:
            op = self.app.pending_ops.get(self.wp.id)
        except AttributeError:
            return None
        return op.form if op else None

    @staticmethod
    def _diff_text(current: str, new_value) -> str:  # noqa: ANN001
        if new_value is None or new_value == current:
            return current or ''
        return f'{current} [bold yellow]→ {new_value}[/bold yellow]'

    def _status_type_project_line(
        self, pending, statuses: dict[int, str], types: dict[int, str]
    ):  # noqa: ANN202
        status = self._diff_text(
            self.wp.status_name, statuses.get(pending.status_id) if pending else None
        )
        type_ = self._diff_text(
            self.wp.type_name, types.get(pending.type_id) if pending else None
        )
        return f'Status: {status}   Type: {type_}   Project: {self.wp.project_name}'

    def _priority_line(self, pending, priorities: dict[int, str]):  # noqa: ANN202
        if not self.wp.priority_name and not (pending and pending.priority_id):
            return None
        new = priorities.get(pending.priority_id) if pending else None
        return f'Priority: {self._diff_text(self.wp.priority_name or "", new)}'

    def _assignee_line(self, pending, users: dict[int, str]):  # noqa: ANN202
        current = self.wp.assignee_name or ''
        new = None
        if pending is not None:
            if pending.assignee_id is not None:
                new = users.get(pending.assignee_id) or f'#{pending.assignee_id}'
            elif pending.unassign:
                new = '(none)'
        if not current and not new:
            return None
        return f'Assignee: {self._diff_text(current, new)}'

    def _start_due_line(self, pending):  # noqa: ANN202
        current_start = self.wp.start_date.isoformat() if self.wp.start_date else ''
        current_due = self.wp.due_date.isoformat() if self.wp.due_date else ''
        new_start = pending.start_date if pending else None
        new_due = pending.due_date if pending else None
        has_anything = any([current_start, current_due, new_start, new_due])
        if not has_anything:
            return None
        start_cell = self._diff_text(current_start or '—', new_start)
        due_cell = self._diff_text(current_due or '—', new_due)
        return f'Start: {start_cell}   Due: {due_cell}'

    # --- actions ---------------------------------------------------------

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_open_browser(self) -> None:
        base_url = self.config.connection.base_url.rstrip('/')
        webbrowser.open(f'{base_url}/work_packages/{self.wp.id}')

    def action_edit(self) -> None:
        modal = UpdateModal(
            remote=self.config.remote, target_count=1, wp=self.wp, client=self.client
        )
        pending = self._pending_form()
        if pending is not None:
            modal.form.merge_from(pending)

        def _on_dismiss(form: UpdateForm | None) -> None:
            if form is None or not form.has_changes:
                return
            fresh_form = UpdateForm()
            fresh_form.merge_from(form)
            self.app.pending_ops.add_or_merge(
                self.wp.id, fresh_form, original_subject=self.wp.subject
            )
            self._refresh_header()
            self._refresh_state_label()

        self.app.push_screen(modal, _on_dismiss)

    def _refresh_state_label(self) -> None:
        from op.tui.app import AppState

        self.app.set_state(AppState.DETAIL, detail=f'OP#{self.wp.id}')

    def _refresh_header(self) -> None:
        """Re-render the meta-label after the wp was updated."""
        try:
            self.query_one('#meta', Label).update(self._meta_text())
        except Exception:  # noqa: BLE001
            pass

    def action_comment(self) -> None:
        async def _submit(text: str | None) -> None:
            if not text:
                return
            if self.client is None:
                self.notify('No API client — comment not sent', severity='warning')
                return
            try:
                await self.client.add_comment(self.wp.id, text)
            except Exception as exc:  # noqa: BLE001
                self.notify(f'Comment failed: {exc}', severity='error', timeout=8)
                return
            self.notify('Comment added', severity='information')
            await self._load_activities()

        self.app.push_screen(CommentModal(), _submit)
