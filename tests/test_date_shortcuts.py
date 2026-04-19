from __future__ import annotations

from datetime import date

import pytest

from op.date_shortcuts import next_free_day, parse_shortcut


class TestLiterals:
    def test_today(self) -> None:
        assert parse_shortcut('today', today=date(2026, 4, 19)) == date(2026, 4, 19)

    def test_today_short(self) -> None:
        assert parse_shortcut('t', today=date(2026, 4, 19)) == date(2026, 4, 19)

    def test_tomorrow(self) -> None:
        assert parse_shortcut('tomorrow', today=date(2026, 4, 19)) == date(2026, 4, 20)

    def test_tom_short(self) -> None:
        assert parse_shortcut('tom', today=date(2026, 4, 19)) == date(2026, 4, 20)

    def test_yesterday(self) -> None:
        assert parse_shortcut('yesterday', today=date(2026, 4, 19)) == date(2026, 4, 18)


class TestWeekdays:
    @pytest.mark.parametrize(
        'shortcut,expected',
        [
            ('mon', date(2026, 4, 20)),
            ('tue', date(2026, 4, 21)),
            ('wed', date(2026, 4, 22)),
            ('thu', date(2026, 4, 23)),
            ('fri', date(2026, 4, 24)),
            ('sat', date(2026, 4, 25)),
            ('sun', date(2026, 4, 26)),
            ('monday', date(2026, 4, 20)),
            ('Friday', date(2026, 4, 24)),
        ],
    )
    def test_weekday_from_sunday(self, shortcut: str, expected: date) -> None:
        # Sunday 2026-04-19 — "mon" is the very next day
        assert parse_shortcut(shortcut, today=date(2026, 4, 19)) == expected

    def test_same_weekday_wraps_to_next_week(self) -> None:
        # Monday → "mon" should not return same day, but 7 days later
        monday = date(2026, 4, 20)
        assert parse_shortcut('mon', today=monday) == date(2026, 4, 27)


class TestRelative:
    def test_plus_days_implicit(self) -> None:
        assert parse_shortcut('+3', today=date(2026, 4, 19)) == date(2026, 4, 22)

    def test_plus_days_explicit(self) -> None:
        assert parse_shortcut('+3d', today=date(2026, 4, 19)) == date(2026, 4, 22)

    def test_plus_weeks(self) -> None:
        assert parse_shortcut('+2w', today=date(2026, 4, 19)) == date(2026, 5, 3)

    def test_minus_days(self) -> None:
        assert parse_shortcut('-1', today=date(2026, 4, 19)) == date(2026, 4, 18)

    def test_minus_weeks(self) -> None:
        assert parse_shortcut('-1w', today=date(2026, 4, 19)) == date(2026, 4, 12)


class TestNextWorkday:
    def test_saturday_to_monday(self) -> None:
        assert parse_shortcut('next', today=date(2026, 4, 18)) == date(2026, 4, 20)

    def test_sunday_to_monday(self) -> None:
        assert parse_shortcut('next', today=date(2026, 4, 19)) == date(2026, 4, 20)

    def test_weekday_returns_same_day(self) -> None:
        # Tuesday → Tuesday (today is already a workday)
        assert parse_shortcut('next', today=date(2026, 4, 21)) == date(2026, 4, 21)

    def test_aliases(self) -> None:
        assert parse_shortcut('nf', today=date(2026, 4, 18)) == date(2026, 4, 20)


class TestIsoPassthrough:
    def test_iso_date(self) -> None:
        assert parse_shortcut('2026-05-01') == date(2026, 5, 1)


class TestEdgeCases:
    def test_empty_string(self) -> None:
        assert parse_shortcut('') is None

    def test_whitespace(self) -> None:
        assert parse_shortcut('   ', today=date(2026, 4, 19)) is None

    def test_surrounding_whitespace_trimmed(self) -> None:
        assert parse_shortcut('  today  ', today=date(2026, 4, 19)) == date(2026, 4, 19)

    def test_unknown_returns_none(self) -> None:
        assert parse_shortcut('nonsense') is None

    def test_case_insensitive(self) -> None:
        assert parse_shortcut('TODAY', today=date(2026, 4, 19)) == date(2026, 4, 19)


class TestNextFreeDay:
    def test_returns_today_when_today_is_free_workday(self) -> None:
        tuesday = date(2026, 4, 21)
        assert next_free_day(tuesday, busy_days=set()) == tuesday

    def test_skips_weekend(self) -> None:
        saturday = date(2026, 4, 18)
        assert next_free_day(saturday, busy_days=set()) == date(2026, 4, 20)

    def test_skips_busy_day(self) -> None:
        tuesday = date(2026, 4, 21)
        assert next_free_day(tuesday, busy_days={tuesday}) == date(2026, 4, 22)

    def test_skips_multiple_busy_days(self) -> None:
        tuesday = date(2026, 4, 21)
        busy = {tuesday, date(2026, 4, 22), date(2026, 4, 23)}
        assert next_free_day(tuesday, busy_days=busy) == date(2026, 4, 24)

    def test_skips_over_busy_week_end_into_next_monday(self) -> None:
        friday = date(2026, 4, 24)
        # Friday is busy → Mon (skip weekend)
        assert next_free_day(friday, busy_days={friday}) == date(2026, 4, 27)

    def test_busy_days_on_weekend_are_ignored(self) -> None:
        """Saturday/Sunday are never free anyway — whether they're in busy_days is irrelevant."""
        saturday = date(2026, 4, 18)
        # Even if Sat is marked busy, we always skip weekend and check Mon
        assert next_free_day(saturday, busy_days={saturday}) == date(2026, 4, 20)
