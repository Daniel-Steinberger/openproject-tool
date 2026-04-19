from __future__ import annotations

from typing import Iterable


class Selection:
    """Multi-select state for the main task list — tracks chosen task IDs."""

    def __init__(self) -> None:
        self._ids: set[int] = set()

    @property
    def count(self) -> int:
        return len(self._ids)

    def contains(self, task_id: int) -> bool:
        return task_id in self._ids

    def toggle(self, task_id: int) -> None:
        if task_id in self._ids:
            self._ids.discard(task_id)
        else:
            self._ids.add(task_id)

    def invert(self, *, all_ids: Iterable[int]) -> None:
        self._ids = set(all_ids) - self._ids

    def clear(self) -> None:
        self._ids.clear()

    def as_list(self) -> list[int]:
        return sorted(self._ids)
