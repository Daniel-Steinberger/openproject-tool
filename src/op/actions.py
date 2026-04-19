from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from op.api import OpenProjectClient, OpenProjectError
from op.config import update_remote

log = logging.getLogger(__name__)


async def load_remote_data(client: OpenProjectClient, config_path: Path) -> None:
    """Fetch metadata in parallel and write it to the `[remote.*]` config sections.

    Endpoints missing on the target OpenProject instance (HTTP 404) are skipped
    with a warning — the remaining metadata is still synced.
    """
    statuses, types, priorities, projects, users, custom_fields = await asyncio.gather(
        _safe_fetch('statuses', client.get_statuses),
        _safe_fetch('types', client.get_types),
        _safe_fetch('priorities', client.get_priorities),
        _safe_fetch('projects', client.get_projects),
        _safe_fetch('users', client.get_users),
        _safe_fetch('custom_fields', client.get_custom_fields),
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


async def _safe_fetch(label: str, fetch):  # noqa: ANN001, ANN202
    try:
        return await fetch()
    except OpenProjectError as exc:
        if ' returned 404:' in str(exc):
            log.warning('Skipping %s — endpoint not available (%s)', label, exc)
            return []
        raise
