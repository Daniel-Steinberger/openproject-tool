from __future__ import annotations

from textual.binding import Binding
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Select

from op.config import RemoteConfig
from op.tui.update_form import UpdateForm


class UpdateModal(ModalScreen[UpdateForm | None]):
    """Modal dialog for batch-editing fields of the selected tasks.

    `g` applies the pending changes (dismiss with the form),
    `q` / `esc` cancels (dismiss with None).
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
        width: 60;
        height: auto;
    }
    UpdateModal Grid {
        grid-size: 2 4;
        grid-columns: 10 1fr;
        grid-rows: 3 3 3 3;
    }
    """

    def __init__(self, *, remote: RemoteConfig, target_count: int) -> None:
        super().__init__()
        self.form = UpdateForm()
        self._remote = remote
        self._target_count = target_count

    def compose(self):  # noqa: ANN201
        with Vertical():
            yield Label(f'Update {self._target_count} task(s)', id='update-header')
            with Grid():
                yield Label('Status:')
                yield _make_select(self._remote.statuses, id='sel-status')
                yield Label('Type:')
                yield _make_select(self._remote.types, id='sel-type')
                yield Label('Priority:')
                yield _make_select(self._remote.priorities, id='sel-priority')
                yield Label('Assignee:')
                yield _make_select(self._remote.users, id='sel-assignee')
            yield Label('[g] Apply   [q] Cancel', id='update-footer')

    def on_select_changed(self, event: Select.Changed) -> None:
        field_map = {
            'sel-status': 'status_id',
            'sel-type': 'type_id',
            'sel-priority': 'priority_id',
            'sel-assignee': 'assignee_id',
        }
        attr = field_map.get(event.select.id or '')
        if attr is None:
            return
        value = None if event.value is Select.BLANK else event.value
        setattr(self.form, attr, value)

    def action_apply(self) -> None:
        self.dismiss(self.form if self.form.has_changes else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


def _make_select(
    options: dict[int, str], *, id: str
) -> Select[int]:  # noqa: A002 — `id` mirrors Textual API
    return Select[int](
        [(name, oid) for oid, name in sorted(options.items(), key=lambda x: x[1])],
        prompt='— no change —',
        id=id,
        allow_blank=True,
    )
