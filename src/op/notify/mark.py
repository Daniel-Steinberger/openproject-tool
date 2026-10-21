"""Selecting and marking notifications as read.

Marking is the only write this mode performs, so it follows the same
review-before-apply shape as the rest of `op`: a queue collects what would
happen, `apply()` executes it and reports what actually did.
"""

from __future__ import annotations

import logging
import typing as T
from dataclasses import dataclass, field

from op.api import OpenProjectError
from op.notify.analysis import GroupAnalysis

log = logging.getLogger('op.notify.mark')


class _MarkClient(T.Protocol):
    async def mark_read(self, notification_id: int) -> None: ...


@dataclass
class MarkResult:
    marked: int = 0
    failed: list[tuple[int, str]] = field(default_factory=list)


def select_analyses(
    analyses: list[GroupAnalysis],
    *,
    work_package_ids: list[int] | None = None,
    churn: bool = False,
    all_groups: bool = False,
) -> list[GroupAnalysis]:
    """Pick the groups the user asked for. Unknown ids raise rather than pass silently."""
    if all_groups:
        return list(analyses)
    if churn:
        return [a for a in analyses if a.is_churn]
    if not work_package_ids:
        return []

    selected: list[GroupAnalysis] = []
    unknown: list[int] = []
    for wanted in work_package_ids:
        # The user reads work package ids off the report, but a notification id
        # is just as plausible an input — accept either, work package first.
        match = next((a for a in analyses if a.work_package_id == wanted), None)
        if match is None:
            match = next((a for a in analyses if wanted in a.notification_ids), None)
        if match is None:
            unknown.append(wanted)
        elif match not in selected:
            selected.append(match)

    if unknown:
        ids = ', '.join(str(i) for i in unknown)
        raise ValueError(f'nicht in der ungelesenen Inbox gefunden: {ids}')
    return selected


class MarkQueue:
    """Work packages queued for marking, keyed by work package id."""

    def __init__(self) -> None:
        self._entries: dict[object, GroupAnalysis] = {}

    @property
    def count(self) -> int:
        return len(self._entries)

    @property
    def notification_ids(self) -> list[int]:
        seen: dict[int, None] = {}
        for analysis in self._entries.values():
            for notification_id in analysis.notification_ids:
                seen.setdefault(notification_id, None)
        return list(seen)

    def add(self, analysis: GroupAnalysis) -> None:
        key: object = analysis.work_package_id or ('other', tuple(analysis.notification_ids))
        existing = self._entries.get(key)
        if existing is None:
            self._entries[key] = analysis
            return
        merged = list(existing.notification_ids)
        merged.extend(i for i in analysis.notification_ids if i not in merged)
        existing.notification_ids = merged

    def remove(self, work_package_id: int) -> None:
        self._entries.pop(work_package_id, None)

    def contains(self, work_package_id: int | None) -> bool:
        return work_package_id in self._entries

    def all(self) -> list[GroupAnalysis]:
        return list(self._entries.values())

    def clear(self) -> None:
        self._entries.clear()

    async def apply(
        self,
        client: _MarkClient,
        *,
        on_progress: T.Callable[[int, int], None] | None = None,
    ) -> MarkResult:
        """Mark every queued notification, one by one.

        Sequential on purpose: there is no bulk endpoint, the calls are cheap,
        and a partially failed run stays comprehensible this way.
        """
        ids = self.notification_ids
        result = MarkResult()
        for done, notification_id in enumerate(ids, start=1):
            try:
                await client.mark_read(notification_id)
                result.marked += 1
            except OpenProjectError as exc:
                log.warning('marking notification %s failed: %s', notification_id, exc)
                result.failed.append((notification_id, str(exc)))
            if on_progress is not None:
                on_progress(done, len(ids))
        return result
