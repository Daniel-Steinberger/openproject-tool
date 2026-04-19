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

    def _meta_text(self) -> str:
        parts = [
            f'[bold cyan]OP#{self.wp.id}[/bold cyan]  [bold]{self.wp.subject}[/bold]',
            f'Status: {self.wp.status_name}   Type: {self.wp.type_name}   '
            f'Project: {self.wp.project_name}',
        ]
        if self.wp.priority_name:
            parts.append(f'Priority: {self.wp.priority_name}')
        if self.wp.assignee_name:
            parts.append(f'Assignee: {self.wp.assignee_name}')
        return '\n'.join(parts)

    # --- actions ---------------------------------------------------------

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_open_browser(self) -> None:
        base_url = self.config.connection.base_url.rstrip('/')
        webbrowser.open(f'{base_url}/work_packages/{self.wp.id}')

    def action_edit(self) -> None:
        modal = UpdateModal(remote=self.config.remote, target_count=1, wp=self.wp)

        async def _apply(form: UpdateForm | None) -> None:
            if form is None or self.client is None:
                return
            changes = form.api_changes()
            if not changes:
                return
            await self.client.update_work_package(
                self.wp.id, lock_version=self.wp.lock_version, changes=changes
            )

        self.app.push_screen(modal, _apply)

    def action_comment(self) -> None:
        async def _submit(text: str | None) -> None:
            if not text or self.client is None:
                return
            await self.client.add_comment(self.wp.id, text)
            await self._load_activities()

        self.app.push_screen(CommentModal(), _submit)
