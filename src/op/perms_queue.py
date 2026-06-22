"""Pending-membership queue for the `op perms` review-before-apply workflow.

Collects additive membership changes (one per project + principal). Re-queuing
the same (project, principal) merges the role sets (union). Mirrors the
shape/status model of `queue.OperationQueue`.
"""

from __future__ import annotations

import typing as T
from dataclasses import dataclass, field

from op.perms import PendingMembership

OperationStatus = T.Literal['pending', 'running', 'done', 'failed']


@dataclass
class PendingMembershipOp:
    project_id: int
    kind: str            # 'group' | 'user'
    principal_id: int
    role_ids: set[int] = field(default_factory=set)
    status: OperationStatus = 'pending'
    error: str | None = None

    @property
    def key(self) -> tuple[int, str, int]:
        return (self.project_id, self.kind, self.principal_id)


class PermissionQueue:
    """Ordered map of (project, kind, principal) → pending membership op."""

    def __init__(self) -> None:
        self._ops: dict[tuple[int, str, int], PendingMembershipOp] = {}

    @property
    def count(self) -> int:
        return len(self._ops)

    def add(self, pending: PendingMembership) -> None:
        key = (pending.project_id, pending.kind, pending.principal_id)
        existing = self._ops.get(key)
        if existing is None:
            self._ops[key] = PendingMembershipOp(
                project_id=pending.project_id,
                kind=pending.kind,
                principal_id=pending.principal_id,
                role_ids=set(pending.role_ids),
            )
        else:
            existing.role_ids |= set(pending.role_ids)

    def add_many(self, pendings: list[PendingMembership]) -> None:
        for p in pendings:
            self.add(p)

    def remove(self, key: tuple[int, str, int]) -> None:
        self._ops.pop(key, None)

    def all(self) -> list[PendingMembershipOp]:
        return list(self._ops.values())

    def clear(self) -> None:
        self._ops.clear()

    def clear_done(self) -> None:
        self._ops = {k: op for k, op in self._ops.items() if op.status != 'done'}
