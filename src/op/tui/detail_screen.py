from __future__ import annotations

import re
import typing as T
import webbrowser

from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Label, Markdown

from op.config import Config
from op.html_to_markdown import html_to_markdown
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
        # Less-style navigation
        Binding('space', 'page_down', 'Page Down', show=False),
        Binding('greater_than_sign', 'scroll_end', 'End', show=False),
        Binding('less_than_sign', 'scroll_home', 'Home', show=False),
        # Less-style search
        Binding('slash', 'search_forward', 'Search', show=True),
        Binding('question_mark', 'search_backward', 'Search back', show=False),
        Binding('n', 'search_next', 'Next match', show=True),
        Binding('N', 'search_prev', 'Prev match', show=False),
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
    DetailScreen #activities {
        height: auto;
        padding: 0 2;
    }
    DetailScreen .activity-head {
        margin-top: 1;
    }
    DetailScreen #activities Markdown {
        background: $panel;
        padding: 0 1;
        margin-bottom: 1;
    }
    DetailScreen #activities-empty {
        padding: 0 2;
        color: $text-muted;
    }
    DetailScreen #search-bar {
        dock: bottom;
        height: 1;
        background: cyan;
        display: none;
    }
    DetailScreen #search-bar.visible {
        display: block;
    }
    DetailScreen #search-input {
        width: 1fr;
        height: 1;
        padding: 0 1;
        border: none;
        background: cyan;
        color: black;
    }
    DetailScreen #search-input:focus {
        border: none;
        background: cyan;
    }
    DetailScreen #search-input > .input--cursor {
        background: black;
        color: cyan;
    }
    DetailScreen #search-input > .input--placeholder {
        color: black 70%;
    }
    DetailScreen #search-status {
        width: auto;
        height: 1;
        padding: 0 1;
        background: cyan;
        color: black;
        text-style: bold;
    }
    DetailScreen .search-hit-current {
        border-left: thick $warning;
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
        # Search state
        self._activity_widgets: list[tuple[Markdown, str]] = []
        self._search_hits: list[Markdown] = []
        self._current_hit: int = -1
        self._total_matches: int = 0
        self._search_direction: T.Literal['forward', 'backward'] = 'forward'

    def compose(self):  # noqa: ANN201
        yield Header()
        with VerticalScroll():
            yield Label(self._meta_text(), id='meta')
            if self.wp.description:
                yield Markdown(self.wp.description, id='description')
            yield Label('Activity', id='activity-header')
            yield Vertical(id='activities')
        with Horizontal(id='search-bar'):
            yield Input(placeholder='pattern', id='search-input')
            yield Label('', id='search-status')
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
        await self._render_activities()

    async def _render_activities(self) -> None:
        """Mount one Label+Markdown pair per activity so comments render as real Markdown."""
        container = self.query_one('#activities', Vertical)
        await container.remove_children()

        widgets: list = []
        self._activity_widgets = []
        for activity in self._activities:
            source = self._activity_markdown_source(activity)
            if not source:
                continue
            user = self._resolve_user_name(activity)
            when = activity.created_at or ''
            widgets.append(
                Label(
                    f'[bold]{user}[/bold]  [dim]{when}[/dim]',
                    classes='activity-head',
                )
            )
            md = Markdown(source)
            self._activity_widgets.append((md, source))
            widgets.append(md)
        if not widgets:
            widgets.append(Label('(no comments)', id='activities-empty'))
        await container.mount(*widgets)

    def _activity_markdown_source(self, activity: Activity) -> str:
        """Prefer html→markdown when html is present: WYSIWYG content (tables etc.)
        is usually richer in html than in the `raw` markdown source."""
        if activity.comment_html:
            converted = html_to_markdown(activity.comment_html).strip()
            if converted:
                return converted
        return activity.comment or ''

    def _resolve_user_name(self, activity: Activity) -> str:
        """Fallback chain for the author display: link title → remote.users → id → (unknown)."""
        if activity.user_name:
            return activity.user_name
        if activity.user_id is not None:
            remote = self.config.remote
            lookup = {**remote.users, **remote.groups}
            name = lookup.get(activity.user_id)
            if name:
                return name
            return f'User #{activity.user_id}'
        return '(unknown)'

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

    # --- less-style scroll controls ---
    # These delegate to the content VerticalScroll; the default Screen-level
    # action_scroll_* raise SkipAction because the screen itself is not scrollable.

    def action_page_down(self) -> None:
        self._content_scroll().action_page_down()

    def action_scroll_end(self) -> None:
        self._content_scroll().scroll_end(animate=False)

    def action_scroll_home(self) -> None:
        self._content_scroll().scroll_home(animate=False)

    def _content_scroll(self) -> VerticalScroll:
        return self.query_one(VerticalScroll)

    # --- less-style search ---

    def action_search_forward(self) -> None:
        self._search_direction = 'forward'
        self._open_search_input()

    def action_search_backward(self) -> None:
        self._search_direction = 'backward'
        self._open_search_input()

    def action_search_next(self) -> None:
        self._advance_hit(+1 if self._search_direction == 'forward' else -1)

    def action_search_prev(self) -> None:
        self._advance_hit(-1 if self._search_direction == 'forward' else +1)

    def _open_search_input(self) -> None:
        bar = self.query_one('#search-bar', Horizontal)
        if 'visible' not in bar.classes:
            bar.add_class('visible')
        try:
            self.query_one(Footer).display = False
        except Exception:  # noqa: BLE001
            pass
        input_ = self.query_one('#search-input', Input)
        input_.value = ''
        input_.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != 'search-input':
            return
        self._run_search(event.value)
        # Hide bar, return focus to content so the list is scrollable again
        bar = self.query_one('#search-bar', Horizontal)
        bar.remove_class('visible')
        try:
            self.query_one(Footer).display = True
        except Exception:  # noqa: BLE001
            pass
        self._content_scroll().focus()

    def _run_search(self, pattern: str) -> None:
        self._clear_search_marks()
        # Always restore the original markdown source — previous search may have
        # wrapped matches in <mark> tags.
        self._restore_markdown_sources()
        if not pattern:
            self._search_hits = []
            self._total_matches = 0
            self._current_hit = -1
            self._update_search_status()
            return
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)

        total = 0
        hits: list[Markdown] = []
        for widget, text in self._searchable_blocks():
            matches = regex.findall(text)
            if not matches:
                continue
            hits.append(widget)
            total += len(matches)
            # Wrap each match in a <mark> tag so the rendered markdown shows the
            # concrete text locations (not just an outline around the whole block).
            highlighted = regex.sub(
                lambda m: f'<mark>{m.group(0)}</mark>', text
            )
            widget.update(highlighted)
        self._search_hits = hits
        self._total_matches = total
        self._current_hit = 0 if hits else -1
        self._focus_hit()
        self._update_search_status()

    def _restore_markdown_sources(self) -> None:
        """Revert any <mark>-wrapping applied by the previous search."""
        if self.wp.description:
            try:
                self.query_one('#description', Markdown).update(self.wp.description)
            except Exception:  # noqa: BLE001
                pass
        for widget, original in self._activity_widgets:
            try:
                widget.update(original)
            except Exception:  # noqa: BLE001
                pass

    def _searchable_blocks(self) -> list[tuple[Markdown, str]]:
        blocks: list[tuple[Markdown, str]] = []
        if self.wp.description:
            try:
                blocks.append(
                    (self.query_one('#description', Markdown), self.wp.description)
                )
            except Exception:  # noqa: BLE001
                pass
        blocks.extend(self._activity_widgets)
        return blocks

    def _advance_hit(self, delta: int) -> None:
        if not self._search_hits:
            return
        self._current_hit = (self._current_hit + delta) % len(self._search_hits)
        self._focus_hit()
        self._update_search_status()

    def _focus_hit(self) -> None:
        self._clear_search_marks()
        if not self._search_hits or self._current_hit < 0:
            return
        widget = self._search_hits[self._current_hit]
        widget.add_class('search-hit-current')
        widget.scroll_visible(animate=False)

    def _clear_search_marks(self) -> None:
        for widget in self.query('.search-hit-current'):
            widget.remove_class('search-hit-current')

    def _update_search_status(self) -> None:
        label = self.query_one('#search-status', Label)
        if self._total_matches == 0:
            label.update('no matches' if self._search_hits is not None else '')
            return
        label.update(
            f'match {self._current_hit + 1}/{len(self._search_hits)} '
            f'({self._total_matches} total)'
        )

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
