from __future__ import annotations

from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Label, TextArea


class CommentModal(ModalScreen[str | None]):
    """Modal for writing a new comment. ctrl+s submits, esc/q cancels."""

    BINDINGS = [
        Binding('ctrl+s', 'submit', 'Submit', show=True),
        Binding('escape', 'cancel', 'Cancel', show=True),
    ]

    DEFAULT_CSS = """
    CommentModal {
        align: center middle;
    }
    CommentModal > Vertical {
        background: $panel;
        border: round $accent;
        padding: 1 2;
        width: 80;
        height: 20;
    }
    CommentModal TextArea {
        height: 1fr;
    }
    """

    def __init__(self, *, initial: str = '') -> None:
        super().__init__()
        self._initial = initial

    @property
    def text(self) -> str:
        return self.query_one(TextArea).text

    @text.setter
    def text(self, value: str) -> None:
        self.query_one(TextArea).text = value

    def compose(self):  # noqa: ANN201
        with Vertical():
            yield Label('New comment')
            yield TextArea(self._initial)
            yield Footer()

    def on_mount(self) -> None:
        self.query_one(TextArea).focus()

    def action_submit(self) -> None:
        text = self.text.strip()
        self.dismiss(text if text else None)

    def action_cancel(self) -> None:
        self.dismiss(None)
