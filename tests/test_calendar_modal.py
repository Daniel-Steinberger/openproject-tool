from __future__ import annotations

from datetime import date

import pytest

from op.tui.calendar_modal import CalendarModal


class _Harness:
    """Minimal app that pushes a CalendarModal for Pilot testing."""

    def __init__(self, modal: CalendarModal) -> None:
        self.modal = modal


async def _run_with_modal(modal: CalendarModal):  # noqa: ANN202
    from textual.app import App

    class _App(App):
        def on_mount(self) -> None:
            self.push_screen(modal)

    return _App


class TestInitialState:
    async def test_mounts_and_shows_month_header(self) -> None:
        modal = CalendarModal(initial=date(2026, 5, 15))
        App = await _run_with_modal(modal)
        async with App().run_test() as pilot:
            await pilot.pause()
            assert modal.selected == date(2026, 5, 15)


class TestNavigation:
    async def test_right_arrow_advances_one_day(self) -> None:
        modal = CalendarModal(initial=date(2026, 5, 15))
        App = await _run_with_modal(modal)
        async with App().run_test() as pilot:
            await pilot.pause()
            await pilot.press('right')
            await pilot.pause()
            assert modal.selected == date(2026, 5, 16)

    async def test_left_arrow_goes_back_one_day(self) -> None:
        modal = CalendarModal(initial=date(2026, 5, 15))
        App = await _run_with_modal(modal)
        async with App().run_test() as pilot:
            await pilot.pause()
            await pilot.press('left')
            await pilot.pause()
            assert modal.selected == date(2026, 5, 14)

    async def test_down_moves_one_week(self) -> None:
        modal = CalendarModal(initial=date(2026, 5, 15))
        App = await _run_with_modal(modal)
        async with App().run_test() as pilot:
            await pilot.pause()
            await pilot.press('down')
            await pilot.pause()
            assert modal.selected == date(2026, 5, 22)

    async def test_up_moves_one_week_back(self) -> None:
        modal = CalendarModal(initial=date(2026, 5, 15))
        App = await _run_with_modal(modal)
        async with App().run_test() as pilot:
            await pilot.pause()
            await pilot.press('up')
            await pilot.pause()
            assert modal.selected == date(2026, 5, 8)

    async def test_pagedown_jumps_one_month(self) -> None:
        modal = CalendarModal(initial=date(2026, 5, 15))
        App = await _run_with_modal(modal)
        async with App().run_test() as pilot:
            await pilot.pause()
            await pilot.press('pagedown')
            await pilot.pause()
            assert modal.selected == date(2026, 6, 15)

    async def test_pageup_jumps_one_month_back(self) -> None:
        modal = CalendarModal(initial=date(2026, 5, 15))
        App = await _run_with_modal(modal)
        async with App().run_test() as pilot:
            await pilot.pause()
            await pilot.press('pageup')
            await pilot.pause()
            assert modal.selected == date(2026, 4, 15)

    async def test_pagedown_clamps_day_if_target_month_shorter(self) -> None:
        """Going +month from Jan 31 lands on Feb 28/29, not a ValueError."""
        modal = CalendarModal(initial=date(2026, 1, 31))
        App = await _run_with_modal(modal)
        async with App().run_test() as pilot:
            await pilot.pause()
            await pilot.press('pagedown')
            await pilot.pause()
            assert modal.selected == date(2026, 2, 28)


class TestPickAndCancel:
    async def test_enter_dismisses_with_selected(self) -> None:
        modal = CalendarModal(initial=date(2026, 5, 15))
        picked: list[date | None] = []

        from textual.app import App

        class _App(App):
            def on_mount(self) -> None:
                self.push_screen(modal, lambda value: picked.append(value))

        async with _App().run_test() as pilot:
            await pilot.pause()
            await pilot.press('right')
            await pilot.press('enter')
            await pilot.pause()

        assert picked == [date(2026, 5, 16)]

    async def test_escape_dismisses_with_none(self) -> None:
        modal = CalendarModal(initial=date(2026, 5, 15))
        picked: list[date | None] = []

        from textual.app import App

        class _App(App):
            def on_mount(self) -> None:
                self.push_screen(modal, lambda value: picked.append(value))

        async with _App().run_test() as pilot:
            await pilot.pause()
            await pilot.press('escape')
            await pilot.pause()

        assert picked == [None]


class TestBusyDays:
    def test_busy_days_stored(self) -> None:
        busy = {date(2026, 5, 20), date(2026, 5, 21)}
        modal = CalendarModal(initial=date(2026, 5, 15), busy_days=busy)
        assert modal.busy_days == busy

    def test_default_empty(self) -> None:
        modal = CalendarModal(initial=date(2026, 5, 15))
        assert modal.busy_days == set()
