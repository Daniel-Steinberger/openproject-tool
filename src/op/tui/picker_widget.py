from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Footer, Input, Label, ListItem, ListView

from rich.text import Text

_BLANK = object()  # sentinel: user chose "— no change —"


class PickerWidget(Widget, can_focus=True):
    """Einzeiliges Auswahlfeld: zeigt aktuellen Wert, Enter öffnet ListPickerScreen."""

    class Changed(Message):
        def __init__(self, widget: 'PickerWidget', value: int | str | None) -> None:
            super().__init__()
            self.widget = widget
            self.value = value  # None = "no change" / blank

    DEFAULT_CSS = """
    PickerWidget {
        height: 1;
        width: 1fr;
        padding: 0;
    }
    PickerWidget > Label {
        height: 1;
        width: 1fr;
        padding: 0 1;
    }
    PickerWidget:focus > Label {
        background: $boost;
        text-style: bold;
    }
    """

    def __init__(
        self,
        options: list[tuple[str, int | str]],
        *,
        id: str,
        value: int | str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._options: list[tuple[str, int | str]] = list(options)
        self._value: int | str | None = value
        self._is_open: bool = False

    def compose(self) -> ComposeResult:
        yield Label(self._format_text(), id='picker-inner')

    def _format_text(self) -> str:
        return self._label_for(self._value)

    def _label_for(self, value: int | str | None) -> str:
        if value is None:
            return '— no change —'
        return next((lbl for lbl, v in self._options if v == value), str(value))

    def _refresh_display(self) -> None:
        try:
            inner = self.query_one('#picker-inner', Label)
        except Exception:  # noqa: BLE001
            return
        inner.update(self._format_text())

    def on_key(self, event: events.Key) -> None:
        if event.key == 'enter' and not self._is_open:
            event.stop()
            self._is_open = True
            self.app.push_screen(
                ListPickerScreen(self._options, current=self._value),
                self._on_picked,
            )

    def _on_picked(self, result: object) -> None:
        self._is_open = False
        if result is None:
            return  # Escape – keine Änderung
        new_value: int | str | None = None if result is _BLANK else result  # type: ignore[assignment]
        self._value = new_value
        self._refresh_display()
        self.post_message(self.Changed(self, new_value))

    def set_options(self, options: list[tuple[str, int | str]]) -> None:
        self._options = list(options)
        self._refresh_display()

    def _reset(self) -> None:
        self._value = None
        self._refresh_display()

    @property
    def value(self) -> int | str | None:
        return self._value

    @value.setter
    def value(self, v: int | str | None) -> None:
        self._value = v
        self._refresh_display()
        self.post_message(self.Changed(self, v))


class CompactInput(Input):
    """Einzeiliger Input ohne Rahmen, einheitlich gestylt für Edit-Dialoge."""

    DEFAULT_CSS = """
    CompactInput {
        border: none;
        height: 1;
        padding: 0 1;
        background: $boost;
    }
    CompactInput:focus {
        border: none;
        height: 1;
        padding: 0 1;
        background: $accent 30%;
    }
    """


class ListPickerScreen(ModalScreen[object]):
    """Kompaktes Overlay zum Auswählen eines Wertes aus einer Liste."""

    BINDINGS = [
        Binding('escape', 'cancel', 'Abbrechen', show=True),
    ]

    DEFAULT_CSS = """
    ListPickerScreen {
        align: center middle;
    }
    ListPickerScreen > Vertical {
        background: $panel;
        border: round $accent;
        padding: 0 1;
        width: 60;
        height: auto;
        max-height: 80%;
    }
    ListPickerScreen ListView {
        height: auto;
        max-height: 20;
    }
    """

    def __init__(
        self,
        options: list[tuple[str, int | str]],
        *,
        current: int | str | None = None,
    ) -> None:
        super().__init__()
        self._items: list[tuple[str, object]] = [('— no change —', _BLANK)] + list(options)
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical():
            yield ListView(id='picker-list')
            yield Footer()

    def on_mount(self) -> None:
        lv = self.query_one(ListView)
        for label, _ in self._items:
            lv.append(ListItem(Label(label)))
        current_idx = 0
        if self._current is not None:
            for i, (_, v) in enumerate(self._items):
                if v == self._current:
                    current_idx = i
                    break
        lv.index = current_idx

    def on_list_view_selected(self, event: ListView.Selected) -> None:  # noqa: ARG002
        lv = self.query_one(ListView)
        idx = lv.index
        if idx is None:
            self.dismiss(None)
            return
        _, val = self._items[idx]
        self.dismiss(val)

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ['CompactInput', 'ListPickerScreen', 'PickerWidget']
