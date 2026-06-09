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
        blank_label: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._options: list[tuple[str, int | str]] = list(options)
        self._value: int | str | None = value
        self._blank_label = blank_label
        self._is_open: bool = False

    def compose(self) -> ComposeResult:
        yield Label(self._format_text(), id='picker-inner')

    def _format_text(self) -> str:
        return self._label_for(self._value)

    def _label_for(self, value: int | str | None) -> str:
        if value is None:
            if self._blank_label:
                return f'— no change — ({self._blank_label})'
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
                ListPickerScreen(
                    self._options, current=self._value, blank_label=self._blank_label
                ),
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


class SearchableInput(CompactInput):
    """CompactInput with a '/' hotkey that opens a search overlay.

    Two Textual quirks shape this:
    - `Input._on_key` inserts printable keys with `prevent_default` *before*
      bindings are resolved, so a binding alone never fires for '/'. The actual
      trigger therefore lives in the `_on_key` override below.
    - The `BINDINGS` entry exists purely so the hotkey shows up as a Footer hint
      while this widget is focused (a widget's own bindings aren't filtered out
      the way screen-level printable-key bindings are).
    """

    BINDINGS = [
        Binding('slash', 'request_search', 'Task-Suche', show=True),
    ]

    class SearchRequested(Message):
        def __init__(self, widget: 'SearchableInput') -> None:
            super().__init__()
            self.widget = widget

    async def _on_key(self, event: events.Key) -> None:
        if event.character == '/':
            event.stop()
            event.prevent_default()
            self.post_message(self.SearchRequested(self))
            return
        await super()._on_key(event)

    def action_request_search(self) -> None:
        self.post_message(self.SearchRequested(self))


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
    ListPickerScreen CompactInput {
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        options: list[tuple[str, int | str]],
        *,
        current: int | str | None = None,
        blank_label: str | None = None,
    ) -> None:
        super().__init__()
        blank = f'— no change — ({blank_label})' if blank_label else '— no change —'
        self._items: list[tuple[str, object]] = [(blank, _BLANK)] + list(options)
        self._current = current
        self._filtered: list[tuple[str, object]] = list(self._items)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield CompactInput(placeholder='Filter…', id='picker-filter')
            yield ListView(id='picker-list')
            yield Footer()

    def on_mount(self) -> None:
        self._rebuild_list(initial=True)
        self.query_one('#picker-filter', CompactInput).focus()

    def _rebuild_list(self, *, initial: bool = False) -> None:
        lv = self.query_one(ListView)
        lv.clear()
        for label, _ in self._filtered:
            lv.append(ListItem(Label(label)))
        current_idx = 0
        if initial and self._current is not None:
            for i, (_, v) in enumerate(self._filtered):
                if v == self._current:
                    current_idx = i
                    break
        if self._filtered:
            lv.index = current_idx

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != 'picker-filter':
            return
        needle = event.value.strip().lower()
        if not needle:
            self._filtered = list(self._items)
        else:
            self._filtered = [
                (label, val)
                for label, val in self._items
                if val is _BLANK or needle in label.lower()
            ]
        self._rebuild_list()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != 'picker-filter':
            return
        lv = self.query_one(ListView)
        idx = lv.index if lv.index is not None else 0
        if not self._filtered:
            return
        idx = max(0, min(idx, len(self._filtered) - 1))
        _, val = self._filtered[idx]
        self.dismiss(val)

    def on_key(self, event: events.Key) -> None:
        if event.key in ('down', 'up', 'pageup', 'pagedown', 'home', 'end'):
            lv = self.query_one(ListView)
            if not self._filtered:
                return
            event.stop()
            cur = lv.index if lv.index is not None else 0
            if event.key == 'down':
                cur = min(cur + 1, len(self._filtered) - 1)
            elif event.key == 'up':
                cur = max(cur - 1, 0)
            elif event.key == 'pagedown':
                cur = min(cur + 10, len(self._filtered) - 1)
            elif event.key == 'pageup':
                cur = max(cur - 10, 0)
            elif event.key == 'home':
                cur = 0
            elif event.key == 'end':
                cur = len(self._filtered) - 1
            lv.index = cur

    def on_list_view_selected(self, event: ListView.Selected) -> None:  # noqa: ARG002
        lv = self.query_one(ListView)
        idx = lv.index
        if idx is None or not self._filtered:
            self.dismiss(None)
            return
        _, val = self._filtered[idx]
        self.dismiss(val)

    def action_cancel(self) -> None:
        self.dismiss(None)


class WorkPackagePickerScreen(ModalScreen[int | None]):
    """Incremental work-package search; returns the picked work-package id.

    Types a substring → live subject search against the API, optionally filtered
    to a set of work-package types (e.g. Projekt/Teilprojekt/Arbeitspaket for a
    parent). Selecting a row dismisses with that work package's id.
    """

    BINDINGS = [
        Binding('escape', 'cancel', 'Abbrechen', show=True),
    ]

    DEFAULT_CSS = """
    WorkPackagePickerScreen {
        align: center middle;
    }
    WorkPackagePickerScreen > Vertical {
        background: $panel;
        border: round $accent;
        padding: 0 1;
        width: 80;
        height: auto;
        max-height: 80%;
    }
    WorkPackagePickerScreen CompactInput {
        margin-bottom: 1;
    }
    WorkPackagePickerScreen ListView {
        height: auto;
        max-height: 20;
    }
    WorkPackagePickerScreen #wp-picker-hint {
        height: auto;
        color: $text-muted;
        padding: 0 1;
    }
    """

    _MIN_CHARS = 2

    def __init__(
        self,
        *,
        client: object,
        type_ids: list[int] | None = None,
        placeholder: str = 'Suche (mind. 2 Zeichen)…',
    ) -> None:
        super().__init__()
        self._client = client
        self._type_ids = list(type_ids or [])
        self._placeholder = placeholder
        self._results: list[tuple[int, str]] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield CompactInput(placeholder=self._placeholder, id='wp-picker-filter')
            yield Label('Tippe, um zu suchen…', id='wp-picker-hint')
            yield ListView(id='wp-picker-list')
            yield Footer()

    def on_mount(self) -> None:
        self.query_one('#wp-picker-filter', CompactInput).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != 'wp-picker-filter':
            return
        needle = event.value.strip()
        if len(needle) < self._MIN_CHARS:
            self._results = []
            self._render_results()
            self._set_hint('Tippe, um zu suchen…')
            return
        self.run_worker(self._do_search(needle), exclusive=True, group='wp-search')

    async def _do_search(self, needle: str) -> None:
        self._set_hint('Suche…')
        filters: list[dict[str, object]] = [
            {'subject': {'operator': '~', 'values': [needle]}}
        ]
        if self._type_ids:
            filters.append(
                {'type_id': {'operator': '=', 'values': [str(t) for t in self._type_ids]}}
            )
        try:
            wps = await self._client.search_work_packages(filters=filters, page_size=50)
        except Exception as exc:  # noqa: BLE001
            self._results = []
            self._render_results()
            self._set_hint(f'Fehler: {exc}')
            return
        self._results = [(wp.id, f'#{wp.id}  {wp.subject}  · {wp.type_name}') for wp in wps]
        self._render_results()
        self._set_hint(f'{len(self._results)} Treffer' if self._results else 'Keine Treffer')

    def _render_results(self) -> None:
        lv = self.query_one(ListView)
        lv.clear()
        for _, label in self._results:
            lv.append(ListItem(Label(label)))
        if self._results:
            lv.index = 0

    def _set_hint(self, text: str) -> None:
        try:
            self.query_one('#wp-picker-hint', Label).update(text)
        except Exception:  # noqa: BLE001
            pass

    def on_key(self, event: events.Key) -> None:
        if event.key in ('down', 'up', 'pageup', 'pagedown', 'home', 'end'):
            if not self._results:
                return
            lv = self.query_one(ListView)
            event.stop()
            cur = lv.index if lv.index is not None else 0
            if event.key == 'down':
                cur = min(cur + 1, len(self._results) - 1)
            elif event.key == 'up':
                cur = max(cur - 1, 0)
            elif event.key == 'pagedown':
                cur = min(cur + 10, len(self._results) - 1)
            elif event.key == 'pageup':
                cur = max(cur - 10, 0)
            elif event.key == 'home':
                cur = 0
            elif event.key == 'end':
                cur = len(self._results) - 1
            lv.index = cur

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != 'wp-picker-filter' or not self._results:
            return
        lv = self.query_one(ListView)
        idx = lv.index if lv.index is not None else 0
        idx = max(0, min(idx, len(self._results) - 1))
        self.dismiss(self._results[idx][0])

    def on_list_view_selected(self, event: ListView.Selected) -> None:  # noqa: ARG002
        lv = self.query_one(ListView)
        idx = lv.index
        if idx is None or not self._results:
            return
        self.dismiss(self._results[idx][0])

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = [
    'CompactInput',
    'ListPickerScreen',
    'PickerWidget',
    'SearchableInput',
    'WorkPackagePickerScreen',
]
