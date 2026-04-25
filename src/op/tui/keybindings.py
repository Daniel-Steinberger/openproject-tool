"""Apply Config keybindings to all TUI screen classes.

Call apply_to_screens(config) once before the App is started. It patches the
class-level BINDINGS and resets _merged_bindings (Textual's binding cache) on
every screen class so Textual picks up the user's keys on next instantiation.
"""
from __future__ import annotations

from textual.binding import Binding
from textual.dom import DOMNode

from op.config import Config


def _set_bindings(cls: type[DOMNode], bindings: list[Binding]) -> None:
    """Replace BINDINGS on cls and refresh Textual's per-class binding cache."""
    cls.BINDINGS = bindings
    cls._merged_bindings = cls._merge_bindings()


def apply_to_screens(config: Config) -> None:
    """Patch BINDINGS on all screen classes from config."""
    from op.tui.applying_screen import ApplyingScreen
    from op.tui.calendar_modal import CalendarModal
    from op.tui.comment_modal import CommentModal
    from op.tui.detail_screen import DetailScreen
    from op.tui.filter_screen import FilterScreen
    from op.tui.main_screen import MainScreen
    from op.tui.project_filter_screen import ProjectFilterScreen
    from op.tui.review_screen import ReviewScreen
    from op.tui.update_modal import UpdateModal

    kb = config.keybindings

    m = kb.main
    _set_bindings(MainScreen, [
        Binding(m.toggle, 'toggle_selected', 'Toggle', show=True),
        Binding(m.invert, 'invert_selection', 'Invert', show=True),
        Binding(m.ignore, 'ignore_task', 'Ignore', show=True),
        Binding(m.ignore, 'unignore_task', 'Unignore', show=True),
        Binding(m.edit, 'update', 'Edit', show=True),
        Binding(m.apply, 'review_queue', 'Apply', show=True),
        Binding(m.filter, 'open_filter', 'Filter', show=True),
        Binding(m.open, 'open_browser', 'Open', show=True),
        Binding(m.project_filter, 'toggle_project_filter', 'Proj-Filter', show=True),
        Binding(m.quit, 'quit', 'Quit', show=True),
    ])

    d = kb.detail
    _set_bindings(DetailScreen, [
        Binding(d.close, 'close', 'Back', show=True),
        Binding('escape', 'close', 'Back', show=False),
        Binding(d.edit, 'edit', 'Edit', show=True),
        Binding(d.comment, 'comment', 'Comment', show=True),
        Binding(d.open, 'open_browser', 'Open', show=True),
        # Less-style navigation (not configurable — standard pager conventions)
        Binding('space', 'page_down', 'Page Down', show=False),
        Binding('greater_than_sign', 'scroll_end', 'End', show=False),
        Binding('less_than_sign', 'scroll_home', 'Home', show=False),
        Binding(d.search, 'search_forward', 'Search', show=True),
        Binding('question_mark', 'search_backward', 'Search back', show=False),
        Binding(d.search_next, 'search_next', 'Next match', show=True),
        Binding('N', 'search_prev', 'Prev match', show=False),
    ])

    u = kb.update_modal
    _set_bindings(UpdateModal, [
        Binding(u.apply, 'apply', 'Apply', show=True),
        Binding(u.cancel, 'cancel', 'Cancel', show=True),
        Binding('escape', 'cancel', 'Cancel', show=False),
        Binding(u.pick_date, 'pick_date', 'Calendar', show=True, priority=True),
        Binding(u.today, 'insert_today', 'Today', show=True, priority=True),
        Binding(u.next_free, 'insert_next_free', 'Next free', show=True, priority=True),
    ])

    f = kb.filter
    _set_bindings(FilterScreen, [
        Binding(f.apply, 'apply', 'Apply', show=True, priority=True),
        Binding('escape', 'cancel', 'Cancel', show=True),
    ])

    pf = kb.project_filter
    _set_bindings(ProjectFilterScreen, [
        Binding(pf.toggle, 'toggle', 'Toggle', show=True),
        Binding(pf.invert, 'invert', 'Invert', show=True),
        Binding(pf.save, 'save_close', 'Save', show=True),
        Binding('enter', 'save_close', 'Save', show=False),
        Binding('escape', 'discard_close', 'Cancel', show=True),
    ])

    r = kb.review
    _set_bindings(ReviewScreen, [
        Binding(r.edit, 'edit', 'Edit', show=True),
        Binding(r.delete, 'delete', 'Delete', show=True),
        Binding(r.apply, 'apply_all', 'Apply', show=True),
        Binding(r.back, 'back', 'Back', show=True),
    ])

    c = kb.comment
    _set_bindings(CommentModal, [
        Binding(c.submit, 'submit', 'Submit', show=True),
        Binding('escape', 'cancel', 'Cancel', show=True),
    ])

    cal = kb.calendar
    _set_bindings(CalendarModal, [
        Binding('enter', 'pick', 'Pick', show=True),
        Binding('escape', 'cancel', 'Cancel', show=True),
        Binding('q', 'cancel', 'Cancel', show=False),
        Binding('left', 'prev_day', 'Prev day', show=False),
        Binding('right', 'next_day', 'Next day', show=False),
        Binding('up', 'prev_week', 'Prev week', show=False),
        Binding('down', 'next_week', 'Next week', show=False),
        Binding(cal.prev_month, 'prev_month', 'Prev month', show=True),
        Binding(cal.next_month, 'next_month', 'Next month', show=True),
        Binding(cal.today, 'jump_today', 'Today', show=True),
        Binding(cal.next_free, 'jump_next_free', 'Next free', show=True),
    ])

    a = kb.applying
    _set_bindings(ApplyingScreen, [
        Binding(a.close, 'close', 'Close', show=True),
    ])

    from op.tui.ignore_list_screen import IgnoreListScreen

    il = kb.ignore_list
    _set_bindings(IgnoreListScreen, [
        Binding(il.unignore, 'unignore', 'Unignore', show=True),
        Binding(il.filter_toggle, 'toggle_filter', 'Filter on/off', show=True),
        Binding(il.save, 'close', 'Close', show=True),
        Binding('escape', 'close', 'Close', show=False),
    ])
