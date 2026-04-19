from __future__ import annotations

import typing as T
from datetime import date

from textual.binding import Binding
from textual.containers import Grid, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Label, Select, TextArea

from op.config import RemoteConfig
from op.date_shortcuts import next_free_day, parse_shortcut
from op.models import WorkPackage
from op.tui.calendar_modal import CalendarModal
from op.tui.update_form import UpdateForm

_WORKLOAD_SHORTCUTS = {'next', 'nf'}


class UpdateModal(ModalScreen[UpdateForm | None]):
    """Modal dialog for editing task fields.

    - Link fields (status/type/priority/assignee) are always available.
    - Scalar fields (subject/description/start/due) are only shown for single-task edits,
      because applying them to many tasks at once is rarely what the user wants.
    - `g` applies the pending changes, `q` / `esc` cancels.
    """

    BINDINGS = [
        Binding('g', 'apply', 'Apply', show=True),
        Binding('q', 'cancel', 'Cancel', show=True),
        Binding('escape', 'cancel', 'Cancel', show=False),
        # Date-shortcut bindings — shown conditionally via check_action()
        Binding('ctrl+d', 'pick_date', 'Calendar', show=True, priority=True),
        Binding('ctrl+t', 'insert_today', 'Today', show=True, priority=True),
        Binding('ctrl+n', 'insert_next_free', 'Next free', show=True, priority=True),
    ]

    _DATE_ONLY_ACTIONS = frozenset({'pick_date', 'insert_today', 'insert_next_free'})

    DEFAULT_CSS = """
    UpdateModal {
        align: center middle;
    }
    UpdateModal > Vertical {
        background: $panel;
        border: round $accent;
        padding: 1 2;
        width: 70;
        height: auto;
        max-height: 90%;
    }
    UpdateModal VerticalScroll {
        height: auto;
        max-height: 30;
    }
    UpdateModal Grid {
        grid-size: 2;
        grid-columns: 12 1fr;
        grid-rows: auto;
        height: auto;
    }
    UpdateModal Grid > Label {
        padding-top: 1;
    }
    UpdateModal TextArea {
        height: 5;
    }
    """

    def __init__(
        self,
        *,
        remote: RemoteConfig,
        target_count: int,
        wp: WorkPackage | None = None,
        client: T.Any | None = None,
    ) -> None:
        super().__init__()
        self.form = UpdateForm()
        self._remote = remote
        self._target_count = target_count
        self._wp = wp
        self._show_scalars = target_count == 1
        self._client = client
        # Overridable for deterministic tests (the TUI otherwise uses date.today()).
        self._today_override: date | None = None

    def compose(self):  # noqa: ANN201
        with Vertical():
            yield Label(f'Update {self._target_count} task(s)', id='update-header')
            with VerticalScroll(), Grid():
                yield Label('Status:')
                yield _make_select(self._remote.statuses, id='sel-status')
                yield Label('Type:')
                yield _make_select(self._remote.types, id='sel-type')
                yield Label('Priority:')
                yield _make_select(self._remote.priorities, id='sel-priority')
                yield Label('Assignee:')
                yield _make_assignee_select(self._remote.users, self._remote.groups)
                if self._show_scalars:
                    yield Label('Subject:')
                    yield Input(
                        value=self._wp.subject if self._wp else '',
                        id='input-subject',
                    )
                    yield Label('Start:')
                    yield Input(
                        value=_iso(self._wp.start_date if self._wp else None),
                        placeholder='YYYY-MM-DD, today, +7, mon, next',
                        id='input-start',
                    )
                    yield Label('Due:')
                    yield Input(
                        value=_iso(self._wp.due_date if self._wp else None),
                        placeholder='YYYY-MM-DD, today, +7, mon, next',
                        id='input-due',
                    )
                    yield Label('Description:')
                    yield TextArea(self._wp.description or '' if self._wp else '', id='ta-description')
            yield Footer()

    def on_select_changed(self, event: Select.Changed) -> None:
        select_id = event.select.id or ''
        value = None if event.value is Select.BLANK else event.value

        if select_id == 'sel-assignee':
            if value is None:
                self.form.assignee_id = None
                return
            # Option values are tagged "u:<id>" or "g:<id>" — see _make_assignee_select.
            kind, raw_id = str(value).split(':', 1)
            self.form.set_assignee(principal_id=int(raw_id), is_group=(kind == 'g'))
            return

        field_map = {
            'sel-status': 'status_id',
            'sel-type': 'type_id',
            'sel-priority': 'priority_id',
        }
        attr = field_map.get(select_id)
        if attr is not None:
            setattr(self.form, attr, value)

    def _sync_scalar_inputs_to_form(self) -> None:
        if not self._show_scalars or self._wp is None:
            return
        new_subject = self.query_one('#input-subject', Input).value
        if new_subject != self._wp.subject:
            self.form.subject = new_subject

        original_start = _iso(self._wp.start_date)
        original_due = _iso(self._wp.due_date)
        new_start_raw = self.query_one('#input-start', Input).value.strip()
        new_due_raw = self.query_one('#input-due', Input).value.strip()

        resolved_start = _resolve_date_field(new_start_raw)
        resolved_due = _resolve_date_field(new_due_raw)

        start_changed = resolved_start != original_start
        due_changed = resolved_due != original_due

        if start_changed:
            self.form.start_date = resolved_start or None
            # Auto-copy to due-date when user didn't set it explicitly.
            if not due_changed and not resolved_due:
                self.form.due_date = resolved_start or None

        if due_changed:
            self.form.due_date = resolved_due or None

        new_desc = self.query_one('#ta-description', TextArea).text
        if new_desc != (self._wp.description or ''):
            self.form.description = new_desc

    async def action_apply(self) -> None:
        self._sync_scalar_inputs_to_form()
        await self._apply_workload_shortcut_if_needed()
        self.dismiss(self.form if self.form.has_changes else None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Hide date-shortcut bindings from the footer when no date input is focused."""
        if action in self._DATE_ONLY_ACTIONS and self._focused_date_input() is None:
            return False
        return True

    def action_insert_today(self) -> None:
        """Ctrl+T — fill the focused date input with today."""
        target = self._focused_date_input()
        if target is None:
            return
        today = self._today_override or date.today()
        self._set_date_input(target, today)

    async def action_insert_next_free(self) -> None:
        """Ctrl+N — fill the focused date input with the next workload-free workday."""
        target = self._focused_date_input()
        if target is None:
            return
        today = self._today_override or date.today()
        busy = await self._load_busy_days_silent()
        free = next_free_day(today, busy_days=busy)
        self._set_date_input(target, free)

    def _set_date_input(self, target: Input, value: date) -> None:
        """Write `value` to `target` and, when filling Start and Due is empty, mirror to Due."""
        target.value = value.isoformat()
        if target.id == 'input-start':
            due = self.query_one('#input-due', Input)
            if not due.value.strip():
                due.value = value.isoformat()

    async def action_pick_date(self) -> None:
        """Open a calendar popup for the currently-focused start/due input."""
        target_input = self._focused_date_input()
        if target_input is None:
            return

        initial = parse_shortcut(target_input.value) or (self._today_override or date.today())
        busy = await self._load_busy_days_silent()

        def _on_pick(picked: date | None) -> None:
            if picked is not None:
                target_input.value = picked.isoformat()

        self.app.push_screen(
            CalendarModal(initial=initial, busy_days=busy), _on_pick
        )

    def _focused_date_input(self) -> Input | None:
        focused = self.focused
        if isinstance(focused, Input) and focused.id in ('input-start', 'input-due'):
            return focused
        return None

    async def _load_busy_days_silent(self) -> set[date]:
        if self._client is None:
            return set()
        principal_id = self._effective_assignee_id()
        if principal_id is None:
            return set()
        try:
            return await self._client.get_busy_days(principal_id)
        except Exception:  # noqa: BLE001
            return set()

    async def _apply_workload_shortcut_if_needed(self) -> None:
        """Replace the `next`/`nf` start-date with a workload-aware free day."""
        if not self._show_scalars or self._client is None:
            return
        raw_start = self.query_one('#input-start', Input).value.strip().lower()
        if raw_start not in _WORKLOAD_SHORTCUTS:
            return
        principal_id = self._effective_assignee_id()
        if principal_id is None:
            return
        try:
            busy = await self._client.get_busy_days(principal_id)
        except Exception:  # noqa: BLE001 — TUI must stay usable even if API blips
            return
        today = self._today_override or date.today()
        free = next_free_day(today, busy_days=busy)
        self.form.start_date = free.isoformat()
        raw_due = self.query_one('#input-due', Input).value.strip()
        if not raw_due:
            self.form.due_date = free.isoformat()

    def _effective_assignee_id(self) -> int | None:
        """The assignee whose workload the next-free lookup should target.

        Prefer the assignee selected in the edit dialog (user is reassigning the task);
        fall back to the task's current assignee.
        """
        if self.form.assignee_id is not None:
            return self.form.assignee_id
        if self._wp is not None and self._wp.assignee_id is not None:
            return self._wp.assignee_id
        return None


def _iso(value) -> str:  # noqa: ANN001
    if value is None:
        return ''
    return value.isoformat() if hasattr(value, 'isoformat') else str(value)


def _resolve_date_field(raw: str) -> str:
    """Expand a date shortcut (today, +7, mon, …) to ISO. Returns '' for empty input."""
    if not raw:
        return ''
    resolved = parse_shortcut(raw)
    return resolved.isoformat() if resolved is not None else raw


def _make_select(
    options: dict[int, str], *, id: str
) -> Select[int]:  # noqa: A002 — `id` mirrors Textual API
    return Select[int](
        [(name, oid) for oid, name in sorted(options.items(), key=lambda x: x[1])],
        prompt='— no change —',
        id=id,
        allow_blank=True,
    )


def _make_assignee_select(
    users: dict[int, str], groups: dict[int, str]
) -> Select[str]:
    """Users + groups in one dropdown; option value carries kind prefix u:/g:."""
    options: list[tuple[str, str]] = [
        (name, f'u:{uid}') for uid, name in sorted(users.items(), key=lambda x: x[1])
    ]
    options += [
        (f'[Group] {name}', f'g:{gid}')
        for gid, name in sorted(groups.items(), key=lambda x: x[1])
    ]
    return Select[str](options, prompt='— no change —', id='sel-assignee', allow_blank=True)
