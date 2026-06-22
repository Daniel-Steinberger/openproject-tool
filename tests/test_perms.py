from __future__ import annotations

from op.models import Membership
from op.perms import (
    SourceEntry,
    build_hierarchy,
    build_source_set,
    descendants,
    has_mismatch,
    missing_entries,
    plan_propagation,
    plan_transfer,
    visible_members,
)


def _m(mid: int, kind: str, pid: int, roles: list[int]) -> Membership:
    return Membership(
        id=mid, project_id=106, principal_id=pid, principal_name=f'p{pid}',
        principal_type=kind, role_ids=roles,
    )


class TestSourceSet:
    def test_group_folds_its_members(self) -> None:
        # KB group (id 6) is a member; its members 33/34 also have materialised entries.
        memberships = [
            _m(1, 'group', 6, [3]),
            _m(2, 'user', 33, [3]),   # materialised from group
            _m(3, 'user', 34, [3]),   # materialised from group
            _m(4, 'user', 19, [5]),   # genuine direct member (Project admin)
        ]
        group_members = {6: [33, 34]}
        src = build_source_set(memberships, group_members)
        assert SourceEntry('group', 6, frozenset({3})) in src
        assert SourceEntry('user', 19, frozenset({5})) in src
        # folded-away users do NOT appear as direct sources
        assert not any(e.kind == 'user' and e.principal_id in (33, 34) for e in src)

    def test_user_both_in_group_and_direct_is_folded(self) -> None:
        memberships = [_m(1, 'group', 6, [3]), _m(2, 'user', 33, [3])]
        src = build_source_set(memberships, {6: [33]})
        assert src == {SourceEntry('group', 6, frozenset({3}))}

    def test_visible_members(self) -> None:
        memberships = [_m(1, 'group', 6, [3]), _m(2, 'user', 19, [5])]
        assert visible_members(memberships, {6: [33, 34]}) == {6: [33, 34]}


class TestMissing:
    def test_missing_principal(self) -> None:
        parent = {SourceEntry('group', 6, frozenset({3})), SourceEntry('user', 19, frozenset({5}))}
        child = {SourceEntry('user', 19, frozenset({5}))}
        assert missing_entries(parent, child) == {SourceEntry('group', 6, frozenset({3}))}
        assert has_mismatch(parent, child)

    def test_missing_role_only(self) -> None:
        parent = {SourceEntry('user', 19, frozenset({3, 5}))}
        child = {SourceEntry('user', 19, frozenset({3}))}
        assert missing_entries(parent, child) == {SourceEntry('user', 19, frozenset({5}))}

    def test_no_mismatch_when_child_superset(self) -> None:
        parent = {SourceEntry('group', 6, frozenset({3}))}
        child = {SourceEntry('group', 6, frozenset({3})), SourceEntry('user', 7, frozenset({3}))}
        assert not has_mismatch(parent, child)


class TestPlanTransfer:
    def test_transfer_adds_only_missing(self) -> None:
        src = {SourceEntry('group', 6, frozenset({3})), SourceEntry('user', 19, frozenset({5}))}
        dst = {SourceEntry('user', 19, frozenset({5}))}
        plans = plan_transfer(src, dst, dst_project_id=200)
        assert len(plans) == 1
        p = plans[0]
        assert (p.project_id, p.kind, p.principal_id, p.role_ids) == (200, 'group', 6, {3})


class TestHierarchy:
    def test_build_hierarchy_order(self) -> None:
        projects = {1: 'A', 2: 'B', 3: 'C'}
        parents = {2: 1, 3: 2}
        assert build_hierarchy(projects, parents) == [(1, 0, 'A'), (2, 1, 'B'), (3, 2, 'C')]

    def test_descendants_recursive(self) -> None:
        parents = {2: 1, 3: 2, 4: 1}
        assert sorted(descendants(1, parents)) == [2, 3, 4]

    def test_plan_propagation_recursive(self) -> None:
        # 1 (parent) has group KB(6); 2 (child of 1) and 3 (child of 2) lack it.
        parents = {2: 1, 3: 2}
        kb = SourceEntry('group', 6, frozenset({3}))
        source_sets = {1: {kb}, 2: set(), 3: set()}
        plans = plan_propagation(1, parents, source_sets)
        targets = {(p.project_id, p.kind, p.principal_id) for p in plans}
        assert targets == {(2, 'group', 6), (3, 'group', 6)}

    def test_plan_propagation_skips_already_aligned(self) -> None:
        parents = {2: 1}
        kb = SourceEntry('group', 6, frozenset({3}))
        source_sets = {1: {kb}, 2: {kb}}
        assert plan_propagation(1, parents, source_sets) == []
