from __future__ import annotations

from op.models import Membership
from op.perms import (
    SourceEntry,
    build_footprints,
    build_hierarchy,
    build_source_set,
    descendants,
    footprint_deviation,
    has_mismatch,
    majority_footprint,
    missing_entries,
    plan_propagation,
    plan_transfer,
    user_direct_projects,
    user_groups,
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


def _um(uid: int, project: int, kind: str = 'user', roles: list[int] | None = None) -> Membership:
    return Membership(
        id=uid * 1000 + project, project_id=project, principal_id=uid,
        principal_name=f'u{uid}', principal_type=kind, role_ids=roles or [3],
    )


class TestFootprint:
    def test_user_groups_inverts(self) -> None:
        assert user_groups({6: [33, 34], 7: [34]}) == {33: {6}, 34: {6, 7}}

    def test_user_direct_projects_excludes_group_covered(self) -> None:
        # Project 1: group 6 (members 33,34) + direct user 19. 33 is covered → not direct.
        by_project = {
            1: [_um(6, 1, 'group'), _um(33, 1), _um(19, 1)],
        }
        direct = user_direct_projects(by_project, {6: [33, 34]})
        assert direct == {19: {1}}

    def test_majority_and_deviation(self) -> None:
        # 3 members; majority (>1.5 → ≥2) is in group 6 and project 1.
        # member 33,34 are in group 6 + direct project 1; member 99 only in group 6.
        all_group_members = {6: [33, 34, 99]}
        direct = {33: {1}, 34: {1}}  # 99 lacks project 1
        fps = build_footprints([33, 34, 99], all_group_members, direct)
        maj = majority_footprint(fps)
        assert ('group', 6) in maj
        assert ('project', 1) in maj  # 2 of 3 → majority
        # 99 deviates: lacks ('project', 1)
        assert footprint_deviation(fps[99], maj) == {('project', 1)}
        assert footprint_deviation(fps[33], maj) == set()

    def test_no_majority_below_three_members(self) -> None:
        fps = build_footprints([33, 34], {6: [33, 34]}, {33: {1}})
        assert majority_footprint(fps) == set()
