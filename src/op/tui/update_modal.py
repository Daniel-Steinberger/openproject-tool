from __future__ import annotations

from textual.binding import Binding
from textual.containers import Grid, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Label, Select, TextArea

from op.config import RemoteConfig
from op.date_shortcuts import parse_shortcut
from op.models import WorkPackage
from op.tui.update_form import UpdateForm


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
    ]

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
    ) -> None:
        super().__init__()
        self.form = UpdateForm()
        self._remote = remote
        self._target_count = target_count
        self._wp = wp
        self._show_scalars = target_count == 1

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

    def action_apply(self) -> None:
        self._sync_scalar_inputs_to_form()
        self.dismiss(self.form if self.form.has_changes else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


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
