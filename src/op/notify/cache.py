"""Disk cache for per-work-package analyses.

A local model takes seconds per group; re-running the triage after marking a few
notifications should not pay that again. The key ties an entry to the exact
input it was derived from — work package, the activities seen, the model and the
prompt — so a changed prompt or a new comment invalidates it by construction.
"""

from __future__ import annotations

import hashlib
import json
import os
import typing as T
from pathlib import Path

from op.notify.models import NotificationGroup


def default_cache_dir() -> Path:
    """XDG-compliant default location for the analysis cache."""
    xdg = os.environ.get('XDG_CACHE_HOME')
    base = Path(xdg) if xdg else Path.home() / '.cache'
    return base / 'openproject-tool' / 'notify'


class AnalysisCache:
    def __init__(self, *, directory: Path | None = None, enabled: bool = True) -> None:
        self._directory = directory or default_cache_dir()
        self._enabled = enabled

    @staticmethod
    def key_for(group: NotificationGroup, *, model: str, prompt: str) -> str:
        parts = [
            str(group.work_package_id),
            ','.join(str(i) for i in sorted(group.activity_ids)),
            ','.join(str(i) for i in sorted(group.notification_ids)),
            model,
            hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:16],
        ]
        return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:32]

    def get(self, key: str) -> dict[str, T.Any] | None:
        if not self._enabled:
            return None
        try:
            payload = json.loads(self._path(key).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            # A missing, unreadable or half-written entry is simply a miss —
            # never a reason to abort a triage run.
            return None
        return payload if isinstance(payload, dict) else None

    def set(self, key: str, value: dict[str, T.Any]) -> None:
        if not self._enabled:
            return
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            self._path(key).write_text(
                json.dumps(value, ensure_ascii=False), encoding='utf-8'
            )
        except OSError:
            pass  # a cache that cannot be written is still a working tool

    def _path(self, key: str) -> Path:
        return self._directory / f'{key}.json'
