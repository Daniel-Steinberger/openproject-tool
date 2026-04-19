from __future__ import annotations

import calendar
from datetime import date, timedelta

from rich.text import Text
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Label

from op.date_shortcuts import next_free_day


class CalendarModal(ModalScreen[date | None]):
    """Month-view calendar picker.

    Navigation:
      ←/→   previous / next day
      ↑/↓   previous / next week
      PgUp/PgDn  previous / next month
      Enter pick the selected date, Esc/q cancel

    Days in `busy_days` are rendered in a distinct colour so the user can
    avoid scheduling on already-occupied days.
    """

    BINDINGS = [
        Binding('enter', 'pick', 'Pick', show=True),
        Binding('escape', 'cancel', 'Cancel', show=True),
        Binding('q', 'cancel', 'Cancel', show=False),
        Binding('left', 'prev_day', 'Prev day', show=False),
        Binding('right', 'next_day', 'Next day', show=False),
        Binding('up', 'prev_week', 'Prev week', show=False),
        Binding('down', 'next_week', 'Next week', show=False),
        Binding('pageup', 'prev_month', 'Prev month', show=True),
        Binding('pagedown', 'next_month', 'Next month', show=True),
        Binding('ctrl+t', 'jump_today', 'Today', show=True),
        Binding('ctrl+n', 'jump_next_free', 'Next free', show=True),
    ]

    DEFAULT_CSS = """
    CalendarModal {
        align: center middle;
    }
    CalendarModal > Vertical {
        background: $panel;
        border: round $accent;
        padding: 1 2;
        width: 60;
        height: auto;
    }
    """

    def __init__(
        self, *, initial: date, busy_days: set[date] | None = None
    ) -> None:
        super().__init__()
        self.selected: date = initial
        self.busy_days: set[date] = busy_days or set()
        # Overridable for deterministic tests.
        self._today_override: date | None = None

    def compose(self):  # noqa: ANN201
        with Vertical():
            yield Label(self.selected.strftime('%B %Y'), id='cal-header')
            yield Label(self._build_grid(), id='cal-grid')
            yield Footer()

    # --- navigation ------------------------------------------------------

    def action_prev_day(self) -> None:
        self.selected -= timedelta(days=1)
        self._refresh_display()

    def action_next_day(self) -> None:
        self.selected += timedelta(days=1)
        self._refresh_display()

    def action_prev_week(self) -> None:
        self.selected -= timedelta(days=7)
        self._refresh_display()

    def action_next_week(self) -> None:
        self.selected += timedelta(days=7)
        self._refresh_display()

    def action_prev_month(self) -> None:
        self.selected = _shift_months(self.selected, -1)
        self._refresh_display()

    def action_next_month(self) -> None:
        self.selected = _shift_months(self.selected, 1)
        self._refresh_display()

    def action_jump_today(self) -> None:
        self.selected = self._today_override or date.today()
        self._refresh_display()

    def action_jump_next_free(self) -> None:
        today = self._today_override or date.today()
        self.selected = next_free_day(today, busy_days=self.busy_days)
        self._refresh_display()

    def action_pick(self) -> None:
        self.dismiss(self.selected)

    def action_cancel(self) -> None:
        self.dismiss(None)

    # --- rendering -------------------------------------------------------
    # NOTE: _do_not_ name this `_render` — Widget._render is a Textual internal
    # that must return a Visual. Overriding it with a None-returning method
    # breaks the entire render pipeline.

    def _refresh_display(self) -> None:
        self.query_one('#cal-header', Label).update(
            self.selected.strftime('%B %Y')
        )
        self.query_one('#cal-grid', Label).update(self._build_grid())

    def _build_grid(self) -> Text:
        """Rendered month grid as a styled rich.Text object.

        Using Text objects (rather than markup strings) sidesteps any issues with
        Label's markup handling — each span carries its own Style.
        """
        grid = Text()
        grid.append('Mo Tu We Th Fr Sa Su\n', style='dim')
        month_cal = calendar.monthcalendar(self.selected.year, self.selected.month)
        for week_index, week in enumerate(month_cal):
            for day_index, day in enumerate(week):
                if day_index > 0:
                    grid.append(' ')
                if day == 0:
                    grid.append('  ')
                    continue
                cell_date = date(self.selected.year, self.selected.month, day)
                cell_text = f'{day:2d}'
                grid.append(cell_text, style=self._style_for(cell_date))
            if week_index < len(month_cal) - 1:
                grid.append('\n')
        return grid

    def _style_for(self, cell_date: date) -> str:
        """Rich style string for a day cell — selected > busy > weekend > default."""
        if cell_date == self.selected:
            return 'bold black on bright_cyan'
        if cell_date in self.busy_days:
            return 'black on yellow'
        if cell_date.weekday() >= 5:
            return 'dim'
        return ''

    # Backwards-compatible accessor used by tests — returns a markup-looking string
    # that retains the style tokens so existing tests can assert on them.
    def _grid_markup(self) -> str:
        lines: list[str] = ['[dim]Mo Tu We Th Fr Sa Su[/dim]']
        month_cal = calendar.monthcalendar(self.selected.year, self.selected.month)
        for week in month_cal:
            cells: list[str] = []
            for day in week:
                if day == 0:
                    cells.append('  ')
                    continue
                cell_date = date(self.selected.year, self.selected.month, day)
                text = f'{day:2d}'
                style = self._style_for(cell_date)
                cells.append(f'[{style}]{text}[/]' if style else text)
            lines.append(' '.join(cells))
        return '\n'.join(lines)


def _shift_months(d: date, delta: int) -> date:
    """Shift `d` by `delta` months, clamping the day to the target month's length."""
    month_index = d.month - 1 + delta
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))
