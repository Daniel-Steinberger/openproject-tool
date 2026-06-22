"""Root Textual app for the `op perms` permission tool.

Separate from OpApp (no task/work-package state). Loads project memberships
live (not from the --load-remote-data cache, which only holds stable metadata),
reconstructs each project's *source set* (groups + direct users), and hosts the
project tree / detail / review / applying screens.
"""

from __future__ import annotations

import asyncio
import typing as T

from textual.app import App

from op.config import Config
from op.models import Membership
from op.perms import SourceEntry, build_source_set
from op.perms_queue import PermissionQueue


class PermsApp(App[None]):
    TITLE = 'op perms'

    CSS = """
    Screen { layers: base overlay; }
    #perms-projects, #perms-detail, #perms-review, #perms-applying {
        height: 1fr;
        scrollbar-size-horizontal: 0;
        overflow-x: hidden;
    }
    #perms-applying-progress { dock: bottom; width: 100%; height: 1; }
    #perms-applying-errors {
        height: auto; max-height: 10; border-top: solid $error;
        background: $panel; padding: 0 1; display: none;
    }
    #perms-applying-errors.visible { display: block; }
    """

    def __init__(
        self,
        *,
        config: Config,
        client: T.Any,
        start_project: int | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.client = client
        self.start_project = start_project
        self.perms_queue = PermissionQueue()

        self.projects: dict[int, str] = dict(config.remote.projects)
        self.parents: dict[int, int] = dict(config.remote.project_parents)
        self.roles: dict[int, str] = {}
        self.memberships: dict[int, list[Membership]] = {}
        self.group_members: dict[int, list[int]] = {}
        self.source_sets: dict[int, set[SourceEntry]] = {}
        self.loaded = False

    def on_mount(self) -> None:
        from op.tui.perms_projects_screen import PermsProjectsScreen

        self.push_screen(PermsProjectsScreen())

    async def load_data(self) -> None:
        """Fetch roles, all project memberships and the referenced group member lists,
        then compute the source set per project. Idempotent."""
        if self.loaded:
            return
        roles = await self.client.get_roles()
        self.roles = {r.id: r.name for r in roles}

        project_ids = list(self.projects)
        results = await asyncio.gather(
            *(self.client.get_memberships(pid) for pid in project_ids),
            return_exceptions=True,
        )
        for pid, res in zip(project_ids, results):
            self.memberships[pid] = [] if isinstance(res, Exception) else res

        group_ids = {
            m.principal_id
            for ms in self.memberships.values()
            for m in ms
            if m.principal_type == 'group' and m.principal_id is not None
        }
        gm = await asyncio.gather(
            *(self.client.get_group_members(gid) for gid in group_ids),
            return_exceptions=True,
        )
        for gid, res in zip(group_ids, gm):
            self.group_members[gid] = [] if isinstance(res, Exception) else res

        self.source_sets = {
            pid: build_source_set(ms, self.group_members)
            for pid, ms in self.memberships.items()
        }
        self.loaded = True

    def source_set(self, project_id: int) -> set[SourceEntry]:
        return self.source_sets.get(project_id, set())

    def role_label(self, role_ids: T.Iterable[int]) -> str:
        return ', '.join(self.roles.get(r, f'#{r}') for r in role_ids)

    def principal_label(self, kind: str, principal_id: int) -> str:
        if kind == 'group':
            return self.config.remote.groups.get(principal_id, f'Gruppe #{principal_id}')
        return self.config.remote.users.get(principal_id, f'User #{principal_id}')
