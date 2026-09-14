"""Models for the notification inbox.

A notification itself carries no content — it points at a work package and at
the single activity that triggered it. Everything readable is fetched
separately, which is why `Notification` is mostly a bundle of links.
"""

from __future__ import annotations

import typing as T

from pydantic import BaseModel, ConfigDict

from op.models import id_from_href

_WORK_PACKAGE_HREF = '/work_packages/'


def _link(payload: dict[str, T.Any], name: str) -> dict[str, T.Any]:
    link = (payload.get('_links') or {}).get(name)
    return link if isinstance(link, dict) else {}


class Notification(BaseModel):
    model_config = ConfigDict(extra='ignore')

    id: int
    reason: str
    read: bool = False
    created_at: str | None = None
    work_package_id: int | None = None
    work_package_title: str | None = None
    project_id: int | None = None
    project_name: str | None = None
    actor_id: int | None = None
    actor_name: str | None = None
    activity_id: int | None = None
    read_href: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, T.Any]) -> Notification:
        resource = _link(payload, 'resource')
        resource_href = resource.get('href') or ''
        project = _link(payload, 'project')
        actor = _link(payload, 'actor')
        return cls(
            id=payload['id'],
            reason=payload.get('reason') or '',
            read=bool(payload.get('readIAN')),
            created_at=payload.get('createdAt'),
            # Notifications can point at news, wiki pages and more; only work
            # packages are grouped and summarised, so the id stays None otherwise.
            work_package_id=(
                id_from_href(resource_href) if _WORK_PACKAGE_HREF in resource_href else None
            ),
            work_package_title=resource.get('title'),
            project_id=id_from_href(project.get('href')),
            project_name=project.get('title'),
            actor_id=id_from_href(actor.get('href')),
            actor_name=actor.get('title'),
            activity_id=id_from_href(_link(payload, 'activity').get('href')),
            read_href=_link(payload, 'readIAN').get('href'),
        )


class NotificationGroup(BaseModel):
    """All unread notifications for one work package, in arrival order."""

    model_config = ConfigDict(extra='ignore')

    work_package_id: int | None
    title: str
    project_name: str | None
    notifications: list[Notification]

    @classmethod
    def from_notifications(cls, notifications: list[Notification]) -> NotificationGroup:
        if not notifications:
            raise ValueError('a notification group needs at least one notification')
        first = notifications[0]
        return cls(
            work_package_id=first.work_package_id,
            title=first.work_package_title or f'#{first.work_package_id}',
            project_name=first.project_name,
            notifications=list(notifications),
        )

    @property
    def count(self) -> int:
        return len(self.notifications)

    @property
    def notification_ids(self) -> list[int]:
        return [n.id for n in self.notifications]

    @property
    def activity_ids(self) -> list[int]:
        return [n.activity_id for n in self.notifications if n.activity_id is not None]

    @property
    def reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for n in self.notifications:
            counts[n.reason] = counts.get(n.reason, 0) + 1
        return counts

    @property
    def actors(self) -> list[str]:
        """Distinct actor names, in order of first appearance."""
        seen: dict[str, None] = {}
        for n in self.notifications:
            if n.actor_name:
                seen.setdefault(n.actor_name, None)
        return list(seen)

    @property
    def latest(self) -> str | None:
        stamps = [n.created_at for n in self.notifications if n.created_at]
        return max(stamps) if stamps else None

    @property
    def earliest(self) -> str | None:
        stamps = [n.created_at for n in self.notifications if n.created_at]
        return min(stamps) if stamps else None

    @property
    def is_mentioned(self) -> bool:
        """True when at least one notification is a direct @-mention."""
        return 'mentioned' in self.reason_counts
