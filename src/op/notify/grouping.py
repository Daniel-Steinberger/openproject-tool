"""Bundle the flat notification list into one group per work package."""

from __future__ import annotations

from op.notify.models import Notification, NotificationGroup


def group_by_work_package(notifications: list[Notification]) -> list[NotificationGroup]:
    """One group per work package, newest group first, chronological inside a group.

    Notifications that do not point at a work package (news, wiki pages) are kept
    as single-entry groups — dropping them silently would hide the very thing the
    inbox is for.
    """
    buckets: dict[object, list[Notification]] = {}
    for notification in notifications:
        # Without a work package id every notification stands on its own.
        key: object = notification.work_package_id or ('other', notification.id)
        buckets.setdefault(key, []).append(notification)

    groups = [
        NotificationGroup.from_notifications(sorted(bucket, key=_sort_key))
        for bucket in buckets.values()
    ]
    groups.sort(key=lambda g: g.latest or '', reverse=True)
    return groups


def _sort_key(notification: Notification) -> tuple[str, int]:
    return (notification.created_at or '', notification.id)
