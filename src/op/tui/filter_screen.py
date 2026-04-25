"""FilterScreen — interactively adjust the task-list query while in the TUI."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Label

from op.search import SearchQuery, parse, query_to_field_strings

_FIELD_IDS: list[tuple[str, str, str]] = [
    # (label, input-id, query-key)
    ('Words',    'input-words',    'words'),
    ('Status',   'input-status',   'status'),
    ('Type',     'input-type',     'type'),
    ('Priority', 'input-priority', 'priority'),
    ('Project',  'input-project',  'project'),
    ('Assignee', 'input-assignee', 'assignee'),
    ('Author',   'input-author',   'author'),
    ('PM',       'input-pm',       'pm'),
]


class FilterScreen(ModalScreen[SearchQuery | None]):
    """Modal dialog that lets the user rewrite the current SearchQuery.

    Inputs carry the current values as comma-separated strings. Pressing `g`
    re-parses them back into a SearchQuery (using the same parse() path the CLI
    takes), and dismisses with that query. `q` / `esc` dismisses with None.
    """

    BINDINGS = [
        Binding('ctrl+g', 'apply', 'Apply', show=True, priority=True),
        Binding('escape', 'cancel', 'Cancel', show=True),
    ]

    DEFAULT_CSS = """
    FilterScreen {
        align: center middle;
    }
    FilterScreen > Vertical {
        background: $panel;
        border: round $accent;
        padding: 1 2;
        width: 70;
        height: auto;
    }
    FilterScreen Grid {
        grid-size: 2;
        grid-columns: 12 1fr;
        grid-rows: auto;
    }
    FilterScreen Grid > Label {
        padding-top: 1;
    }
    """

    def __init__(self, *, query: SearchQuery) -> None:
        super().__init__()
        self._initial = query_to_field_strings(query)

    def compose(self):  # noqa: ANN201
        with Vertical():
            yield Label('Filter tasks', id='filter-header')
            with Grid():
                for label, input_id, key in _FIELD_IDS:
                    yield Label(f'{label}:')
                    yield Input(
                        value=self._initial.get(key, ''),
                        placeholder='comma-separated (use * for any)' if key != 'words' else 'space-separated',
                        id=input_id,
                    )
            yield Footer()

    def action_apply(self) -> None:
        self.dismiss(self._build_query())

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Pressing Enter in any filter input submits the whole query."""
        self.dismiss(self._build_query())

    def _build_query(self) -> SearchQuery:
        """Join the inputs into CLI-style tokens and hand them to parse()."""
        tokens: list[str] = []
        for _, input_id, key in _FIELD_IDS:
            value = self.query_one(f'#{input_id}', Input).value.strip()
            if not value:
                continue
            if key == 'words':
                tokens.extend(value.split())
            else:
                tokens.append(f'{key}={value}')
        return parse(tokens)
