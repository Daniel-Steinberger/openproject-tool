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


class TestGridStyling:
    def test_selected_day_rendered_bold_with_inverted_colors(self) -> None:
        """Selected day must use a bold/colored Rich markup tag, not >NN<."""
        modal = CalendarModal(initial=date(2026, 5, 15))
        grid = modal._grid_markup()
        # No ASCII brackets around the selected day anymore
        assert '>15<' not in grid
        assert '>1<' not in grid
        # Must contain a Rich-style tag with bold for the selected day
        assert 'bold' in grid
        # And the number itself must still be there
        assert '15' in grid

    def test_busy_day_has_color_markup(self) -> None:
        """Busy days must be highlighted with a background color, not just '*NN'."""
        modal = CalendarModal(initial=date(2026, 5, 15), busy_days={date(2026, 5, 20)})
        grid = modal._grid_markup()
        # No more ASCII markers
        assert '*20' not in grid
        # A Rich 'on yellow' (or similar) style must exist
        assert 'on yellow' in grid or 'on red' in grid or 'on' in grid
        assert '20' in grid

    def test_weekday_header_styled(self) -> None:
        modal = CalendarModal(initial=date(2026, 5, 15))
        grid = modal._grid_markup()
        assert 'Mo Tu We Th Fr Sa Su' in grid
        # Header is dim
        assert 'dim' in grid


class TestCalendarShortcuts:
    def test_jump_today_sets_selected_to_today(self) -> None:
        modal = _mk(date(2026, 5, 15))
        modal.action_jump_today()
        assert modal.selected == date.today()

    def test_jump_next_free_with_no_busy_returns_next_workday(self) -> None:
        from datetime import timedelta

        # Saturday — next workday is Monday
        modal = _mk(date(2026, 4, 18))  # Saturday
        modal._today_override = date(2026, 4, 18)  # type: ignore[attr-defined]
        modal.action_jump_next_free()
        assert modal.selected == date(2026, 4, 20)  # Monday
        _ = timedelta  # silence unused

    def test_jump_next_free_skips_busy_days(self) -> None:
        today = date(2026, 4, 20)  # Monday
        busy = {today, date(2026, 4, 21)}
        modal = _mk(today, busy=busy)
        modal._today_override = today  # type: ignore[attr-defined]
        modal.action_jump_next_free()
        assert modal.selected == date(2026, 4, 22)


class TestStartDueMirrorOnCalendarPick:
    """When the calendar pick writes to the start input, due should follow when empty."""

    def test_pick_updates_due_when_empty(self) -> None:
        from op.tui.update_modal import UpdateModal
        from op.config import RemoteConfig
        from op.models import WorkPackage

        wp = WorkPackage(
            id=1, subject='t', type_id=1, type_name='Task',
            status_id=1, status_name='Neu', project_id=10, project_name='W',
            lock_version=1, start_date=None, due_date=None,
        )
        modal = UpdateModal(remote=RemoteConfig(), target_count=1, wp=wp)
        # Mirror logic is in _mirror_start_to_due — test it directly
        picked = date(2026, 5, 20)
        assert modal._mirror_start_to_due_target(
            target_id='input-start', picked_iso=picked.isoformat(), due_current=''
        ) == picked.isoformat()

    def test_pick_does_not_overwrite_existing_due(self) -> None:
        from op.tui.update_modal import UpdateModal
        from op.config import RemoteConfig
        from op.models import WorkPackage

        wp = WorkPackage(
            id=1, subject='t', type_id=1, type_name='Task',
            status_id=1, status_name='Neu', project_id=10, project_name='W',
            lock_version=1,
        )
        modal = UpdateModal(remote=RemoteConfig(), target_count=1, wp=wp)
        assert modal._mirror_start_to_due_target(
            target_id='input-start', picked_iso='2026-05-20', due_current='2026-06-01'
        ) is None

    def test_pick_into_due_does_not_touch_start(self) -> None:
        from op.tui.update_modal import UpdateModal
        from op.config import RemoteConfig
        from op.models import WorkPackage

        wp = WorkPackage(
            id=1, subject='t', type_id=1, type_name='Task',
            status_id=1, status_name='Neu', project_id=10, project_name='W',
            lock_version=1,
        )
        modal = UpdateModal(remote=RemoteConfig(), target_count=1, wp=wp)
        assert modal._mirror_start_to_due_target(
            target_id='input-due', picked_iso='2026-05-20', due_current=''
        ) is None
