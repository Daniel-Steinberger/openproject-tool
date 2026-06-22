"""Pure permission logic for the `op perms` tool.

OpenProject's v3 API exposes no `inherited_from` marker on memberships, so we
reconstruct the *source* of a project's permissions from sets:

- group memberships  (principal is a group)
- direct users       (user memberships not covered by any member group)

The per-user entries OpenProject materialises from a group membership are NOT
treated as their own source — they are folded under their group. Transfer and
hierarchy-propagation therefore always operate on the source set (groups +
direct users); the target project re-materialises its own per-user entries.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from op.models import Membership


def build_hierarchy(
    projects: dict[int, str], parents: dict[int, int]
) -> list[tuple[int, int, str]]:
    """Return [(project_id, depth, name)] in parent-before-child order."""
    children: dict[int | None, list[int]] = {}
    for pid in projects:
        parent = parents.get(pid)
        children.setdefault(parent, []).append(pid)
    for group in children.values():
        group.sort(key=lambda pid: projects[pid].lower())

    result: list[tuple[int, int, str]] = []

    def _walk(parent: int | None, depth: int) -> None:
        for pid in children.get(parent, []):
            result.append((pid, depth, projects[pid]))
            _walk(pid, depth + 1)

    all_parent_keys = set(children.keys())
    roots: set[int | None] = {None}
    for parent in all_parent_keys:
        if parent is None or parent not in projects:
            roots.add(parent)
    for root in sorted(roots, key=lambda k: (k is None, k or 0)):
        _walk(root, 0)
    return result


def children_map(parents: dict[int, int]) -> dict[int, list[int]]:
    """parent_id -> [direct child ids]."""
    out: dict[int, list[int]] = {}
    for child, parent in parents.items():
        out.setdefault(parent, []).append(child)
    return out


def descendants(root_id: int, parents: dict[int, int]) -> list[int]:
    """All descendant project ids of root_id (recursive, excludes root itself)."""
    kids = children_map(parents)
    result: list[int] = []
    stack = list(kids.get(root_id, []))
    while stack:
        pid = stack.pop()
        result.append(pid)
        stack.extend(kids.get(pid, []))
    return result


@dataclass(frozen=True)
class SourceEntry:
    """One source-of-permission entry: a group or a direct user with its roles."""

    kind: str           # 'group' | 'user'
    principal_id: int
    role_ids: frozenset[int]


def build_source_set(
    memberships: list[Membership], group_members: dict[int, list[int]]
) -> set[SourceEntry]:
    """Reconstruct the source set of a project from its memberships.

    `group_members` maps group_id -> member user ids for the groups that are
    members of this project. Users covered by such a group are folded away.
    """
    groups = [m for m in memberships if m.principal_type == 'group']
    covered: set[int] = set()
    for g in groups:
        if g.principal_id is not None:
            covered.update(group_members.get(g.principal_id, []))

    out: set[SourceEntry] = set()
    for g in groups:
        if g.principal_id is not None:
            out.add(SourceEntry('group', g.principal_id, frozenset(g.role_ids)))
    for m in memberships:
        if m.principal_type == 'user' and m.principal_id is not None:
            if m.principal_id in covered:
                continue  # visible via a group → not a direct source
            out.add(SourceEntry('user', m.principal_id, frozenset(m.role_ids)))
    return out


def visible_members(
    memberships: list[Membership], group_members: dict[int, list[int]]
) -> dict[int, list[int]]:
    """group_id -> user ids that gain access through that (project-member) group."""
    out: dict[int, list[int]] = {}
    for m in memberships:
        if m.principal_type == 'group' and m.principal_id is not None:
            out[m.principal_id] = list(group_members.get(m.principal_id, []))
    return out


def missing_entries(
    parent_set: set[SourceEntry], child_set: set[SourceEntry]
) -> set[SourceEntry]:
    """Source entries present in the parent but missing (by principal) in the child.

    Compares per principal: an entry is missing if the child has no entry for
    that (kind, principal_id), OR the child's roles for it don't cover the
    parent's roles (additive — missing roles count too).
    """
    child_by_principal: dict[tuple[str, int], frozenset[int]] = {}
    for e in child_set:
        key = (e.kind, e.principal_id)
        child_by_principal[key] = child_by_principal.get(key, frozenset()) | e.role_ids

    out: set[SourceEntry] = set()
    for e in parent_set:
        have = child_by_principal.get((e.kind, e.principal_id))
        if have is None:
            out.add(e)
        elif not e.role_ids <= have:
            out.add(SourceEntry(e.kind, e.principal_id, e.role_ids - have))
    return out


def has_mismatch(parent_set: set[SourceEntry], child_set: set[SourceEntry]) -> bool:
    return bool(missing_entries(parent_set, child_set))


@dataclass
class PendingMembership:
    """A planned additive membership change for one project + principal."""

    project_id: int
    kind: str            # 'group' | 'user'
    principal_id: int
    role_ids: set[int] = field(default_factory=set)


def _pending_from_missing(project_id: int, missing: set[SourceEntry]) -> list[PendingMembership]:
    return [
        PendingMembership(project_id, e.kind, e.principal_id, set(e.role_ids))
        for e in missing
    ]


def plan_transfer(
    src_set: set[SourceEntry], dst_set: set[SourceEntry], dst_project_id: int
) -> list[PendingMembership]:
    """Additive transfer of src's source entries into dst."""
    return _pending_from_missing(dst_project_id, missing_entries(src_set, dst_set))


def plan_propagation(
    root_id: int,
    parents: dict[int, int],
    source_sets: dict[int, set[SourceEntry]],
) -> list[PendingMembership]:
    """Recursively align every descendant of root_id with its own parent.

    For each descendant we add the source entries its direct parent has but it
    lacks. Walking top-down means a fix on an upper level is seen by the levels
    below within the same pass.
    """
    plans: list[PendingMembership] = []
    # Effective (post-fix) source set per project as we walk down.
    effective: dict[int, set[SourceEntry]] = {
        root_id: set(source_sets.get(root_id, set()))
    }
    for child in descendants(root_id, parents):
        parent = parents.get(child)
        parent_set = effective.get(parent, source_sets.get(parent, set()))
        child_set = set(source_sets.get(child, set()))
        missing = missing_entries(parent_set, child_set)
        if missing:
            plans.extend(_pending_from_missing(child, missing))
        # child now effectively has parent's entries too (for deeper levels)
        effective[child] = child_set | parent_set
    return plans
