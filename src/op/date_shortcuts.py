from __future__ import annotations

import re
from datetime import date, timedelta

_WEEKDAYS: dict[str, int] = {
    'mon': 0, 'monday': 0,
    'tue': 1, 'tuesday': 1,
    'wed': 2, 'wednesday': 2,
    'thu': 3, 'thursday': 3,
    'fri': 4, 'friday': 4,
    'sat': 5, 'saturday': 5,
    'sun': 6, 'sunday': 6,
}

_RELATIVE_RE = re.compile(r'^([+-])(\d+)([dw])?$')


def parse_shortcut(value: str, *, today: date | None = None) -> date | None:
    """Interpret a date shortcut typed by the user.

    Supports:
      - today, t, tomorrow, tom, yesterday
      - weekday names (mon..sun, monday..sunday) — next occurrence, wraps to +7 days
        when `today` itself matches the requested weekday
      - next, nf — next work day (Mon–Fri), returns `today` itself if it is already a workday
      - +N / +Nd / +Nw / -N / -Nd / -Nw — relative in days/weeks
      - ISO dates (YYYY-MM-DD) pass through

    Returns `None` when the value is empty, whitespace-only, or not recognised.
    """
    if not value or not value.strip():
        return None
    stripped = value.strip()
    lower = stripped.lower()
    now = today or date.today()

    if lower in ('today', 't'):
        return now
    if lower in ('tomorrow', 'tom'):
        return now + timedelta(days=1)
    if lower == 'yesterday':
        return now - timedelta(days=1)
    if lower in ('next', 'nf'):
        return _next_workday(now)

    if lower in _WEEKDAYS:
        target = _WEEKDAYS[lower]
        delta = (target - now.weekday()) % 7 or 7
        return now + timedelta(days=delta)

    match = _RELATIVE_RE.match(lower)
    if match:
        sign, amount_str, unit = match.groups()
        days = int(amount_str) * (7 if unit == 'w' else 1)
        if sign == '-':
            days = -days
        return now + timedelta(days=days)

    try:
        return date.fromisoformat(stripped)
    except ValueError:
        return None


def _next_workday(start: date) -> date:
    d = start
    while d.weekday() >= 5:  # Sat=5, Sun=6
        d += timedelta(days=1)
    return d
