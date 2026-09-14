"""Apply the `[keybindings.notify_*]` config sections to the notify screens.

Same mechanism as `op.tui.keybindings`: patch the class-level BINDINGS and drop
Textual's merged-binding cache before the app instantiates the screens.
"""

from __future__ import annotations

from textual.binding import Binding

from op.config import Config
from op.tui.keybindings import _set_bindings


def apply_to_notify_screens(config: Config) -> None:
    from op.notify.tui.detail_screen import NotifyDetailScreen
    from op.notify.tui.list_screen import NotifyListScreen
    from op.notify.tui.review_screen import NotifyReviewScreen

    kb = config.keybindings
    li = kb.notify_list
    _set_bindings(NotifyListScreen, [
        Binding(li.toggle, 'toggle_selected', 'Markieren', show=True),
        Binding(li.invert, 'invert_selection', 'Invertieren', show=True),
        Binding(li.mark_churn, 'select_churn', 'Rauschen', show=True),
        Binding(li.mark_all, 'select_all', 'Alle', show=True),
        Binding(li.apply, 'review', 'Review', show=True),
        Binding(li.reload, 'reload', 'Neu laden', show=False),
        Binding(li.open, 'open_browser', 'Browser', show=True),
        Binding(li.quit, 'quit', 'Beenden', show=True),
    ])

    de = kb.notify_detail
    _set_bindings(NotifyDetailScreen, [
        Binding(de.mark, 'toggle_mark', 'Gelesen', show=True),
        Binding(de.prev, 'previous', 'Zurück', show=True),
        Binding(de.next, 'next', 'Weiter', show=True),
        Binding(de.open, 'open_browser', 'Browser', show=True),
        Binding(de.close, 'close', 'Liste', show=True),
        Binding('escape', 'close', 'Liste', show=False),
    ])

    rv = kb.review
    _set_bindings(NotifyReviewScreen, [
        Binding(rv.delete, 'delete', 'Entfernen', show=True),
        Binding(rv.apply, 'apply', 'Anwenden', show=True),
        Binding(rv.back, 'back', 'Zurück', show=True),
        Binding('escape', 'back', 'Zurück', show=False),
    ])
