from __future__ import annotations

from datetime import date

import pytest

from op.date_shortcuts import parse_shortcut


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
