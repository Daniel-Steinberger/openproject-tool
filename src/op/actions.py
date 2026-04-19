from __future__ import annotations

import asyncio
from pathlib import Path

from op.api import OpenProjectClient
from op.config import update_remote


async def load_remote_data(client: OpenProjectClient, config_path: Path) -> None:
    """Fetch all metadata in parallel and write it to the `[remote.*]` config sections."""
    statuses, types, priorities, projects, users, custom_fields = await asyncio.gather(
        client.get_statuses(),
        client.get_types(),
        client.get_priorities(),
        client.get_projects(),
        client.get_users(),
        client.get_custom_fields(),
    )
    update_remote(
        config_path,
        statuses={s.id: s.name for s in statuses},
        types={t.id: t.name for t in types},
        priorities={p.id: p.name for p in priorities},
        projects={p.id: p.name for p in projects},
        users={u.id: u.name for u in users},
        custom_fields={cf.id: cf.name for cf in custom_fields},
    )
