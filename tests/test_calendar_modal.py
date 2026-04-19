from __future__ import annotations

from datetime import date

from op.tui.calendar_modal import CalendarModal, _shift_months


def _mk(initial: date, busy: set[date] | None = None) -> CalendarModal:
    """Create a CalendarModal and stub out its rendering side-effects for unit testing."""
    modal = CalendarModal(initial=initial, busy_days=busy)
    modal._refresh_display = lambda: None  # type: ignore[assignment]
    return modal


class TestInitialState:
    def test_preserves_initial(self) -> None:
        modal = CalendarModal(initial=date(2026, 5, 15))
        assert modal.selected == date(2026, 5, 15)


class TestDayNavigation:
    def test_next_day(self) -> None:
        modal = _mk(date(2026, 5, 15))
        modal.action_next_day()
        assert modal.selected == date(2026, 5, 16)

    def test_prev_day(self) -> None:
        modal = _mk(date(2026, 5, 15))
        modal.action_prev_day()
        assert modal.selected == date(2026, 5, 14)

    def test_next_day_crosses_month(self) -> None:
        modal = _mk(date(2026, 5, 31))
        modal.action_next_day()
        assert modal.selected == date(2026, 6, 1)


class TestWeekNavigation:
    def test_next_week(self) -> None:
        modal = _mk(date(2026, 5, 15))
        modal.action_next_week()
        assert modal.selected == date(2026, 5, 22)

    def test_prev_week(self) -> None:
        modal = _mk(date(2026, 5, 15))
        modal.action_prev_week()
        assert modal.selected == date(2026, 5, 8)


class TestMonthNavigation:
    def test_next_month(self) -> None:
        modal = _mk(date(2026, 5, 15))
        modal.action_next_month()
        assert modal.selected == date(2026, 6, 15)

    def test_prev_month(self) -> None:
        modal = _mk(date(2026, 5, 15))
        modal.action_prev_month()
        assert modal.selected == date(2026, 4, 15)

    def test_next_month_clamps_day(self) -> None:
        modal = _mk(date(2026, 1, 31))
        modal.action_next_month()
        # Feb has 28 days in 2026
        assert modal.selected == date(2026, 2, 28)

    def test_prev_month_over_year_boundary(self) -> None:
        modal = _mk(date(2026, 1, 15))
        modal.action_prev_month()
        assert modal.selected == date(2025, 12, 15)


class TestShiftMonths:
    def test_positive_shift(self) -> None:
        assert _shift_months(date(2026, 1, 15), 2) == date(2026, 3, 15)

    def test_negative_shift(self) -> None:
        assert _shift_months(date(2026, 3, 15), -2) == date(2026, 1, 15)

    def test_year_forward(self) -> None:
        assert _shift_months(date(2026, 12, 5), 1) == date(2027, 1, 5)

    def test_year_backward(self) -> None:
        assert _shift_months(date(2026, 1, 5), -1) == date(2025, 12, 5)

    def test_clamps_to_month_end(self) -> None:
        assert _shift_months(date(2026, 3, 31), -1) == date(2026, 2, 28)
        assert _shift_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


class TestBusyDays:
    def test_stored(self) -> None:
        busy = {date(2026, 5, 20), date(2026, 5, 21)}
        modal = CalendarModal(initial=date(2026, 5, 15), busy_days=busy)
        assert modal.busy_days == busy

    def test_default_empty(self) -> None:
        modal = CalendarModal(initial=date(2026, 5, 15))
        assert modal.busy_days == set()

    def test_grid_includes_markers_for_selected_and_busy(self) -> None:
        """The grid markup must contain distinct markers for selected and busy days."""
        busy = {date(2026, 5, 20)}
        modal = CalendarModal(initial=date(2026, 5, 15), busy_days=busy)
        grid = modal._grid_markup()
        # Selected day 15 is marked
        assert '>15<' in grid or '>1<5' in grid
        # Busy day 20 is marked (different from selected)
        assert '*20' in grid or ' *20'[-3:] in grid
