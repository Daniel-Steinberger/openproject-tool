from __future__ import annotations

import typing as T

import pytest

from op.config import Config, ConnectionConfig, DefaultsConfig, RemoteConfig
from op.models import Membership, Role
from op.tui.perms_app import PermsApp
from op.tui.perms_projects_screen import PermsProjectsScreen


def _membership(mid: int, kind: str, pid: int, project: int, roles: list[int]) -> Membership:
    return Membership(
        id=mid, project_id=project, principal_id=pid, principal_name=f'p{pid}',
        principal_type=kind, role_ids=roles,
    )


class FakeClient:
    """Records create/patch calls; serves a fixed membership/group dataset.

    Projects: 1 "Ober" (parent), 2 "Unter" (child of 1).
    Project 1 has group KB(6) (members 33,34); project 2 has nothing.
    """

    def __init__(self) -> None:
        self.created: list[tuple] = []
        self.patched: list[tuple] = []
        self._memberships = {
            1: [
                _membership(10, 'group', 6, 1, [3]),
                _membership(11, 'user', 33, 1, [3]),  # materialised
                _membership(12, 'user', 34, 1, [3]),  # materialised
            ],
            2: [],
        }

    async def get_roles(self) -> list[Role]:
        return [Role(id=3, name='Member'), Role(id=5, name='Project admin')]

    async def get_memberships(self, project_id: int) -> list[Membership]:
        return self._memberships.get(project_id, [])

    async def get_group_members(self, group_id: int) -> list[int]:
        return [33, 34] if group_id == 6 else []

    async def create_membership(self, project_id, principal_id, role_ids, *, principal_type='user'):  # noqa: ANN001
        self.created.append((project_id, principal_type, principal_id, tuple(role_ids)))
        return _membership(99, principal_type, principal_id, project_id, list(role_ids))

    async def update_membership_roles(self, membership_id, role_ids):  # noqa: ANN001
        self.patched.append((membership_id, tuple(role_ids)))
        return _membership(membership_id, 'user', 0, 0, list(role_ids))


def _config() -> Config:
    return Config(
        connection=ConnectionConfig(base_url='https://op.example.com'),
        defaults=DefaultsConfig(),
        remote=RemoteConfig(
            projects={1: 'Ober', 2: 'Unter'},
            project_parents={2: 1},
            groups={6: 'KB'},
            users={33: 'Grit', 34: 'Christian', 19: 'Martin'},
        ),
    )


@pytest.fixture
def app_factory() -> T.Callable[..., PermsApp]:
    def _make(start: int | None = None) -> PermsApp:
        return PermsApp(config=_config(), client=FakeClient(), start_project=start)
    return _make


class TestProjectsScreen:
    async def test_loads_and_shows_hierarchy(self, app_factory) -> None:  # noqa: ANN001
        from textual.widgets import DataTable

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            assert app.loaded
            table = app.screen.query_one('#perms-projects', DataTable)
            assert table.row_count == 2  # Ober + Unter

    async def test_child_flagged_as_mismatch(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, PermsProjectsScreen)
            # Unter (2) lacks KB → mismatch flag
            assert '▲' in str(screen._flag_for(2))
            # Ober (1) is a root → no flag
            assert '▲' not in str(screen._flag_for(1))

    async def test_fix_queues_propagation(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            screen._move_cursor_to(1)  # Ober
            await pilot.pause()
            screen.action_fix()
            await pilot.pause()
            # KB group should be queued for project 2
            ops = app.perms_queue.all()
            assert any(o.project_id == 2 and o.kind == 'group' and o.principal_id == 6 for o in ops)


class TestApply:
    async def test_apply_creates_missing_group_membership(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            screen._move_cursor_to(1)
            await pilot.pause()
            screen.action_fix()
            await pilot.pause()
            screen.action_review()
            await pilot.pause()
            app.screen.action_apply()
            # let the apply worker run
            for _ in range(6):
                await pilot.pause()
            assert (2, 'group', 6, (3,)) in app.client.created


class TestDetailScreen:
    async def test_detail_folds_group_members(self, app_factory) -> None:  # noqa: ANN001
        from textual.widgets import DataTable
        from op.tui.perms_detail_screen import PermsDetailScreen

        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            app.push_screen(PermsDetailScreen(1))
            await pilot.pause()
            table = app.screen.query_one('#perms-detail', DataTable)
            # 1 group row + 2 folded members = 3 rows (no separate direct-user rows)
            assert table.row_count == 3
