from __future__ import annotations

from op.perms_queue import (
    AddGroupMembers,
    AddProjectMembership,
    CloneInto,
    CreateUserClone,
    PermissionQueue,
)


def test_membership_dedups_per_principal_and_unions_roles() -> None:
    q = PermissionQueue()
    q.add(AddProjectMembership(project_id=200, kind='group', principal_id=6, role_ids={3}))
    q.add(AddProjectMembership(project_id=200, kind='group', principal_id=6, role_ids={5}))
    assert q.count == 1
    assert q.all()[0].role_ids == {3, 5}


def test_distinct_principals_are_separate() -> None:
    q = PermissionQueue()
    q.add_many([
        AddProjectMembership(project_id=200, kind='group', principal_id=6, role_ids={3}),
        AddProjectMembership(project_id=200, kind='user', principal_id=19, role_ids={5}),
        AddProjectMembership(project_id=201, kind='group', principal_id=6, role_ids={3}),
    ])
    assert q.count == 3


def test_group_members_merge_into_one_action() -> None:
    q = PermissionQueue()
    q.add(AddGroupMembers(group_id=6, user_ids={33}))
    q.add(AddGroupMembers(group_id=6, user_ids={34}))
    assert q.count == 1
    assert q.all()[0].user_ids == {33, 34}


def test_clone_into_merges_groups_and_memberships() -> None:
    q = PermissionQueue()
    q.add(CloneInto(target_user_id=33, group_ids={6}, memberships={(1, frozenset({3}))}))
    q.add(CloneInto(target_user_id=33, group_ids={7}))
    assert q.count == 1
    op = q.all()[0]
    assert op.group_ids == {6, 7}
    assert op.memberships == {(1, frozenset({3}))}


def test_create_user_keyed_by_login() -> None:
    q = PermissionQueue()
    q.add(CreateUserClone(login='a@x', email='a@x', first_name='A', last_name='B'))
    q.add(CreateUserClone(login='a@x', email='a@x', first_name='A', last_name='B'))
    assert q.count == 1


def test_clear_done_keeps_pending() -> None:
    q = PermissionQueue()
    q.add(AddProjectMembership(project_id=200, kind='group', principal_id=6, role_ids={3}))
    q.add(AddProjectMembership(project_id=200, kind='user', principal_id=19, role_ids={5}))
    ops = q.all()
    ops[0].status = 'done'
    q.clear_done()
    assert q.count == 1
    assert q.all()[0].principal_id == 19
