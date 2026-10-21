from __future__ import annotations

from op.notify.grouping import group_by_work_package
from op.notify.models import Notification

from .test_models import notification_payload


def notif(**kwargs) -> Notification:
    return Notification.from_api(notification_payload(**kwargs))


class TestGroupByWorkPackage:
    def test_groups_notifications_of_same_work_package(self) -> None:
        groups = group_by_work_package([
            notif(notif_id=1, wp_id=100, created_at='2026-09-01T10:00:00Z'),
            notif(notif_id=2, wp_id=100, created_at='2026-09-02T10:00:00Z'),
        ])
        assert len(groups) == 1
        assert groups[0].work_package_id == 100
        assert groups[0].notification_ids == [1, 2]

    def test_newest_group_first(self) -> None:
        groups = group_by_work_package([
            notif(notif_id=1, wp_id=100, created_at='2026-09-01T10:00:00Z'),
            notif(notif_id=2, wp_id=200, created_at='2026-09-05T10:00:00Z'),
            notif(notif_id=3, wp_id=300, created_at='2026-09-03T10:00:00Z'),
        ])
        assert [g.work_package_id for g in groups] == [200, 300, 100]

    def test_notifications_inside_group_are_chronological(self) -> None:
        groups = group_by_work_package([
            notif(notif_id=1, wp_id=100, created_at='2026-09-05T10:00:00Z'),
            notif(notif_id=2, wp_id=100, created_at='2026-09-01T10:00:00Z'),
        ])
        assert groups[0].notification_ids == [2, 1]

    def test_non_work_package_notifications_are_kept(self) -> None:
        payload = notification_payload(notif_id=9)
        payload['_links']['resource'] = {'href': '/api/v3/news/7', 'title': 'Neuigkeit'}
        groups = group_by_work_package([Notification.from_api(payload)])
        assert len(groups) == 1
        assert groups[0].work_package_id is None
        assert groups[0].title == 'Neuigkeit'

    def test_empty_input(self) -> None:
        assert group_by_work_package([]) == []
