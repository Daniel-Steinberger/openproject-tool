"""Pending-operation queue for aptitude-style review-before-apply workflow."""

from __future__ import annotations

import typing as T
from dataclasses import dataclass, field

from op.tui.update_form import UpdateForm

OperationStatus = T.Literal['pending', 'running', 'done', 'failed']


@dataclass
class PendingOperation:
    task_id: int
    form: UpdateForm
    status: OperationStatus = 'pending'
    error: str | None = None
    # The WorkPackage we last saw in the list — used for lockVersion at apply time
    # and to render original→new diffs in the review screen.
    original_subject: str | None = None

    def summary(
        self,
        *,
        statuses: dict[int, str] | None = None,
        types: dict[int, str] | None = None,
        priorities: dict[int, str] | None = None,
        projects: dict[int, str] | None = None,
        users: dict[int, str] | None = None,
    ) -> str:
        return self.form.summary(
            statuses=statuses, types=types, priorities=priorities,
            projects=projects, users=users,
        )


class OperationQueue:
    """Ordered map of task-id → pending operation.

    New edits on an already-queued task are merged into the existing form
    (last-writer-wins per field) — the queue stays length-constant in that case.
    """

    def __init__(self) -> None:
        self._ops: dict[int, PendingOperation] = {}

    @property
    def count(self) -> int:
        return len(self._ops)

    def add_or_merge(
        self, task_id: int, form: UpdateForm, *, original_subject: str | None = None
    ) -> None:
        existing = self._ops.get(task_id)
        if existing is None:
            self._ops[task_id] = PendingOperation(
                task_id=task_id, form=form, original_subject=original_subject
            )
            return
        existing.form.merge_from(form)
        if original_subject is not None:
            existing.original_subject = original_subject

    def remove(self, task_id: int) -> None:
        self._ops.pop(task_id, None)

    def get(self, task_id: int) -> PendingOperation | None:
        return self._ops.get(task_id)

    def all(self) -> list[PendingOperation]:
        return list(self._ops.values())

    def clear(self) -> None:
        self._ops.clear()

    def clear_done(self) -> None:
        self._ops = {
            tid: op for tid, op in self._ops.items() if op.status != 'done'
        }
