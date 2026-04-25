from __future__ import annotations

import typing as T
from datetime import date

from textual.binding import Binding
from textual.containers import Grid, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Label, TextArea

from op.config import RemoteConfig
from op.date_shortcuts import next_free_day, parse_shortcut
from op.models import WorkPackage
from op.tui.calendar_modal import CalendarModal
from op.tui.picker_widget import CompactInput, PickerWidget
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
        grid-columns: 16 1fr;
        grid-rows: auto;
        height: auto;
    }
    UpdateModal Grid > Label {
        height: 1;
        padding: 0;
    }
    UpdateModal Grid > .ta-label {
        height: 5;
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
        self._today_override: date | None = None

    def compose(self):  # noqa: ANN201
        with Vertical():
            yield Label(f'Update {self._target_count} task(s)', id='update-header')
            with VerticalScroll():
                with Grid():
                    yield Label('Status:')
                    yield _make_picker(self._remote.statuses, id='sel-status')
                    yield Label('Type:')
                    yield _make_picker(self._remote.types, id='sel-type')
                    yield Label('Priority:')
                    yield _make_picker(self._remote.priorities, id='sel-priority')
                    yield Label('Project:')
                    yield _make_picker(self._remote.projects, id='sel-project')
                    yield Label('Assignee:')
                    yield _make_assignee_picker(self._remote.users, self._remote.groups)
                    yield Label('+ Beobachter:')
                    yield _make_picker(self._remote.users, id='sel-add-watcher')
                    yield Label('- Beobachter:')
                    yield _make_picker(self._remote.users, id='sel-remove-watcher')
                    for _cf_id, _cf_users in sorted(self._remote.custom_field_users.items()):
                        _cf_name = self._remote.custom_fields.get(_cf_id, f'CF #{_cf_id}')
                        _initial = (
                            self._wp.custom_field_links.get(_cf_id)
                            if self._wp is not None else None
                        )
                        yield Label(f'{_cf_name}:')
                        yield _make_picker(_cf_users, id=f'sel-cf-{_cf_id}', value=_initial)
                    for _cf_id, _cf_opts in sorted(self._remote.custom_field_options.items()):
                        _cf_name = self._remote.custom_fields.get(_cf_id, f'CF #{_cf_id}')
                        _initial = (
                            self._wp.custom_field_links.get(_cf_id)
                            if self._wp is not None else None
                        )
                        yield Label(f'{_cf_name}:')
                        yield _make_picker(_cf_opts, id=f'sel-cfo-{_cf_id}', value=_initial)
                    if self._show_scalars:
                        yield Label('Subject:')
                        yield CompactInput(
                            value=self._wp.subject if self._wp else '',
                            id='input-subject',
                        )
                        yield Label('Start:')
                        yield CompactInput(
                            value=_iso(self._wp.start_date if self._wp else None),
                            placeholder='YYYY-MM-DD, today, +7, mon, next',
                            id='input-start',
                        )
                        yield Label('Due:')
                        yield CompactInput(
                            value=_iso(self._wp.due_date if self._wp else None),
                            placeholder='YYYY-MM-DD, today, +7, mon, next',
                            id='input-due',
                        )
                        yield Label('Description:', classes='ta-label')
                        yield TextArea(self._wp.description or '' if self._wp else '', id='ta-description')
                info = self._watcher_info_text()
                if info:
                    yield Label(info, id='lbl-watchers-info')
            yield Footer()

    def on_mount(self) -> None:
        if self._show_scalars and self._wp is not None and self._client is not None:
            self.run_worker(self._load_current_watchers(), exclusive=False)

    async def _load_current_watchers(self) -> None:
        try:
            watchers = await self._client.get_watchers(self._wp.id)
        except Exception:  # noqa: BLE001
            return
        if not watchers:
            return
        options = [(w.name, w.id) for w in watchers]
        try:
            self.query_one('#sel-remove-watcher', PickerWidget).set_options(options)
        except Exception:  # noqa: BLE001
            pass

    def _watcher_info_text(self) -> str:
        parts: list[str] = []
        for uid in self.form.add_watcher_ids:
            name = self._remote.users.get(uid, f'#{uid}')
            parts.append(f'+{name}')
        for uid in self.form.remove_watcher_ids:
            name = self._remote.users.get(uid, f'#{uid}')
            parts.append(f'-{name}')
        return f'Geplant: {" ".join(parts)}' if parts else ''

    def on_key(self, event) -> None:  # noqa: ANN001
        """Pfeil hoch/runter navigiert zwischen Feldern (außer in TextArea)."""
        if event.key == 'up':
            event.stop()
            self.focus_previous()
            self.refresh_bindings()
        elif event.key == 'down':
            event.stop()
            self.focus_next()
            self.refresh_bindings()

    def on_picker_widget_changed(self, event: PickerWidget.Changed) -> None:
        picker_id = event.widget.id or ''
        value = event.value  # int | str | None; None = blank/no-change

        if picker_id == 'sel-assignee':
            if value is None:
                self.form.assignee_id = None
                return
            kind, raw_id = str(value).split(':', 1)
            self.form.set_assignee(principal_id=int(raw_id), is_group=(kind == 'g'))
            return

        if picker_id == 'sel-add-watcher':
            if value is not None:
                self.form.add_watcher(int(value))
                event.widget._reset()
            return

        if picker_id == 'sel-remove-watcher':
            if value is not None:
                self.form.remove_watcher(int(value))
                event.widget._reset()
            return

        if picker_id.startswith('sel-cfo-'):
            cf_id = int(picker_id[len('sel-cfo-'):])
            self.form.set_custom_field_option(cf_id, int(value) if value is not None else None)
            return

        if picker_id.startswith('sel-cf-'):
            cf_id = int(picker_id[len('sel-cf-'):])
            self.form.set_custom_field_user(cf_id, int(value) if value is not None else None)
            return

        field_map = {
            'sel-status': 'status_id',
            'sel-type': 'type_id',
            'sel-priority': 'priority_id',
            'sel-project': 'project_id',
        }
        attr = field_map.get(picker_id)
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
        if action in self._DATE_ONLY_ACTIONS and self._focused_date_input() is None:
            return False
        return True

    def action_insert_today(self) -> None:
        target = self._focused_date_input()
        if target is None:
            return
        today = self._today_override or date.today()
        self._set_date_input(target, today)

    async def action_insert_next_free(self) -> None:
        target = self._focused_date_input()
        if target is None:
            return
        today = self._today_override or date.today()
        busy = await self._load_busy_days_silent()
        free = next_free_day(today, busy_days=busy)
        self._set_date_input(target, free)

    def _set_date_input(self, target: Input, value: date) -> None:
        target.value = value.isoformat()
        mirrored = self._mirror_start_to_due_target(
            target_id=target.id or '',
            picked_iso=value.isoformat(),
            due_current=self.query_one('#input-due', Input).value
            if self._show_scalars
            else '',
        )
        if mirrored is not None:
            self.query_one('#input-due', Input).value = mirrored

    @staticmethod
    def _mirror_start_to_due_target(
        *, target_id: str, picked_iso: str, due_current: str
    ) -> str | None:
        if target_id != 'input-start':
            return None
        if not picked_iso:
            return None
        return picked_iso

    async def action_pick_date(self) -> None:
        target_input = self._focused_date_input()
        if target_input is None:
            return

        initial = parse_shortcut(target_input.value) or (self._today_override or date.today())
        busy = await self._load_busy_days_silent()

        def _on_pick(picked: date | None) -> None:
            if picked is not None:
                self._set_date_input(target_input, picked)

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
        except Exception:  # noqa: BLE001
            return
        today = self._today_override or date.today()
        free = next_free_day(today, busy_days=busy)
        self.form.start_date = free.isoformat()
        raw_due = self.query_one('#input-due', Input).value.strip()
        if not raw_due:
            self.form.due_date = free.isoformat()

    def _effective_assignee_id(self) -> int | None:
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
    if not raw:
        return ''
    resolved = parse_shortcut(raw)
    return resolved.isoformat() if resolved is not None else raw


def _make_picker(
    options: dict[int, str], *, id: str, value: int | None = None  # noqa: A002
) -> PickerWidget:
    opts = [(name, oid) for oid, name in sorted(options.items(), key=lambda x: x[1])]
    return PickerWidget(opts, id=id, value=value)


def _make_assignee_picker(users: dict[int, str], groups: dict[int, str]) -> PickerWidget:
    opts: list[tuple[str, str]] = [
        (name, f'u:{uid}') for uid, name in sorted(users.items(), key=lambda x: x[1])
    ]
    opts += [
        (f'[Group] {name}', f'g:{gid}')
        for gid, name in sorted(groups.items(), key=lambda x: x[1])
    ]
    return PickerWidget(opts, id='sel-assignee')
