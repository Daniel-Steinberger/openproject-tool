"""Typed, additive permission actions + their queue for `op perms`.

Each action knows how to describe itself and how to apply itself against the
PermsApp (which holds the client and the loaded membership/group caches). The
review screen renders `describe()`; the applying screen calls `apply()`.

All actions are additive — nothing is ever removed.
"""

from __future__ import annotations

import typing as T
from dataclasses import dataclass, field

OperationStatus = T.Literal['pending', 'running', 'done', 'failed']


async def _ensure_group_member(app: T.Any, group_id: int, user_id: int) -> None:
    """Add user to group if not already a member; keeps app.group_members in sync
    so later actions in the same batch see the update (PATCH replaces the list)."""
    current = list(app.group_members.get(group_id, []))
    if user_id in current:
        return
    new_members = current + [user_id]
    await app.client.set_group_members(group_id, new_members)
    app.group_members[group_id] = new_members


async def _ensure_membership(
    app: T.Any, project_id: int, kind: str, principal_id: int, role_ids: set[int]
) -> None:
    """Create a project membership, or add missing roles if it already exists."""
    existing = None
    for m in app.memberships.get(project_id, []):
        if m.principal_type == kind and m.principal_id == principal_id:
            existing = m
            break
    if existing is None:
        await app.client.create_membership(
            project_id, principal_id, sorted(role_ids), principal_type=kind
        )
    else:
        union = set(existing.role_ids) | role_ids
        if union != set(existing.role_ids):
            await app.client.update_membership_roles(existing.id, sorted(union))


@dataclass
class PermAction:
    status: OperationStatus = 'pending'
    error: str | None = None

    @property
    def key(self) -> tuple:  # pragma: no cover - overridden
        raise NotImplementedError

    def merge(self, other: PermAction) -> None:
        """Fold another action with the same key into this one (default: no-op)."""

    def describe(self, app: T.Any) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    async def apply(self, app: T.Any) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


@dataclass
class AddProjectMembership(PermAction):
    project_id: int = 0
    kind: str = 'user'           # 'user' | 'group'
    principal_id: int = 0
    role_ids: set[int] = field(default_factory=set)

    @property
    def key(self) -> tuple:
        return ('membership', self.project_id, self.kind, self.principal_id)

    def merge(self, other: PermAction) -> None:
        self.role_ids |= other.role_ids  # type: ignore[attr-defined]

    def describe(self, app: T.Any) -> str:
        proj = app.projects.get(self.project_id, str(self.project_id))
        who = app.principal_label(self.kind, self.principal_id)
        warn = ' ⚠ direkt' if self.kind == 'user' else ''
        return f'{proj}: + {who} [{app.role_label(sorted(self.role_ids))}]{warn}'

    async def apply(self, app: T.Any) -> None:
        await _ensure_membership(
            app, self.project_id, self.kind, self.principal_id, self.role_ids
        )


@dataclass
class AddGroupMembers(PermAction):
    group_id: int = 0
    user_ids: set[int] = field(default_factory=set)

    @property
    def key(self) -> tuple:
        return ('groupmembers', self.group_id)

    def merge(self, other: PermAction) -> None:
        self.user_ids |= other.user_ids  # type: ignore[attr-defined]

    def describe(self, app: T.Any) -> str:
        gname = app.config.remote.groups.get(self.group_id, f'Gruppe #{self.group_id}')
        names = ', '.join(
            app.config.remote.users.get(u, f'#{u}') for u in sorted(self.user_ids)
        )
        return f'Gruppe {gname}: + {names}'

    async def apply(self, app: T.Any) -> None:
        for uid in sorted(self.user_ids):
            await _ensure_group_member(app, self.group_id, uid)


@dataclass
class CloneInto(PermAction):
    """Additively align an existing user: add to groups + add direct memberships."""

    target_user_id: int = 0
    group_ids: set[int] = field(default_factory=set)
    memberships: set[tuple[int, frozenset[int]]] = field(default_factory=set)

    @property
    def key(self) -> tuple:
        return ('cloneinto', self.target_user_id)

    def merge(self, other: PermAction) -> None:
        self.group_ids |= other.group_ids  # type: ignore[attr-defined]
        self.memberships |= other.memberships  # type: ignore[attr-defined]

    def describe(self, app: T.Any) -> str:
        who = app.config.remote.users.get(self.target_user_id, f'#{self.target_user_id}')
        parts = [app.config.remote.groups.get(g, f'#{g}') for g in sorted(self.group_ids)]
        parts += [
            f'{app.projects.get(p, p)} ⚠direkt' for p, _ in sorted(self.memberships)
        ]
        return f'{who}: + {", ".join(parts)}'

    async def apply(self, app: T.Any) -> None:
        for gid in sorted(self.group_ids):
            await _ensure_group_member(app, gid, self.target_user_id)
        for pid, roles in self.memberships:
            await _ensure_membership(app, pid, 'user', self.target_user_id, set(roles))


@dataclass
class CreateUserClone(PermAction):
    """Create a user, optionally cloning a template's groups + direct memberships."""

    login: str = ''
    email: str = ''
    first_name: str = ''
    last_name: str = ''
    user_status: str = 'invited'
    template_name: str | None = None
    group_ids: set[int] = field(default_factory=set)
    memberships: set[tuple[int, frozenset[int]]] = field(default_factory=set)

    @property
    def key(self) -> tuple:
        return ('createuser', self.login)

    def describe(self, app: T.Any) -> str:
        base = f'Neuer User {self.email} ({self.user_status})'
        if self.template_name:
            base += (
                f' — wie {self.template_name}: '
                f'{len(self.group_ids)} Gruppe(n), {len(self.memberships)} direkte ⚠'
            )
        return base

    async def apply(self, app: T.Any) -> None:
        user = await app.client.create_user(
            login=self.login, email=self.email,
            first_name=self.first_name, last_name=self.last_name,
            status=self.user_status,
        )
        for gid in sorted(self.group_ids):
            await _ensure_group_member(app, gid, user.id)
        for pid, roles in self.memberships:
            await _ensure_membership(app, pid, 'user', user.id, set(roles))


class PermissionQueue:
    """Ordered, key-deduplicated list of permission actions."""

    def __init__(self) -> None:
        self._ops: dict[tuple, PermAction] = {}

    @property
    def count(self) -> int:
        return len(self._ops)

    def add(self, action: PermAction) -> None:
        existing = self._ops.get(action.key)
        if existing is None:
            self._ops[action.key] = action
        else:
            existing.merge(action)

    def add_many(self, actions: T.Iterable[PermAction]) -> None:
        for a in actions:
            self.add(a)

    def remove(self, key: tuple) -> None:
        self._ops.pop(key, None)

    def all(self) -> list[PermAction]:
        return list(self._ops.values())

    def clear(self) -> None:
        self._ops.clear()

    def clear_done(self) -> None:
        self._ops = {k: op for k, op in self._ops.items() if op.status != 'done'}
