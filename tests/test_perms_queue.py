from __future__ import annotations

from op.perms import PendingMembership
from op.perms_queue import PermissionQueue


def test_add_dedups_per_principal_and_unions_roles() -> None:
    q = PermissionQueue()
    q.add(PendingMembership(200, 'group', 6, {3}))
    q.add(PendingMembership(200, 'group', 6, {5}))
    assert q.count == 1
    op = q.all()[0]
    assert op.role_ids == {3, 5}


def test_distinct_principals_are_separate() -> None:
    q = PermissionQueue()
    q.add_many([
        PendingMembership(200, 'group', 6, {3}),
        PendingMembership(200, 'user', 19, {5}),
        PendingMembership(201, 'group', 6, {3}),
    ])
    assert q.count == 3


def test_clear_done_keeps_pending() -> None:
    q = PermissionQueue()
    q.add(PendingMembership(200, 'group', 6, {3}))
    q.add(PendingMembership(200, 'user', 19, {5}))
    ops = q.all()
    ops[0].status = 'done'
    q.clear_done()
    assert q.count == 1
    assert q.all()[0].principal_id == 19
