from __future__ import annotations

from op.notify.models import Notification, NotificationGroup


def notification_payload(
    *,
    notif_id: int = 1,
    reason: str = 'mentioned',
    wp_id: int = 8202,
    wp_title: str = 'Demo-Deployment',
    actor_id: int = 16,
    actor_name: str = 'Bea Beispiel',
    activity_id: int = 110445,
    created_at: str = '2026-09-14T10:32:00.143Z',
) -> dict:
    return {
        '_type': 'Notification',
        'id': notif_id,
        'readIAN': False,
        'reason': reason,
        'createdAt': created_at,
        'updatedAt': created_at,
        '_embedded': {'details': []},
        '_links': {
            'self': {'href': f'/api/v3/notifications/{notif_id}'},
            'readIAN': {'href': f'/api/v3/notifications/{notif_id}/read_ian', 'method': 'post'},
            'actor': {'href': f'/api/v3/users/{actor_id}', 'title': actor_name},
            'activity': {'href': f'/api/v3/activities/{activity_id}'},
            'resource': {'href': f'/api/v3/work_packages/{wp_id}', 'title': wp_title},
            'project': {'href': '/api/v3/projects/106', 'title': 'Sample project'},
        },
    }


class TestNotification:
    def test_parses_core_fields(self) -> None:
        n = Notification.from_api(notification_payload())
        assert n.id == 1
        assert n.reason == 'mentioned'
        assert n.read is False
        assert n.created_at == '2026-09-14T10:32:00.143Z'

    def test_parses_links(self) -> None:
        n = Notification.from_api(notification_payload())
        assert n.work_package_id == 8202
        assert n.work_package_title == 'Demo-Deployment'
        assert n.actor_id == 16
        assert n.actor_name == 'Bea Beispiel'
        assert n.activity_id == 110445
        assert n.project_id == 106
        assert n.project_name == 'Sample project'
        assert n.read_href == '/api/v3/notifications/1/read_ian'

    def test_tolerates_missing_actor_and_project(self) -> None:
        payload = notification_payload()
        del payload['_links']['actor']
        del payload['_links']['project']
        n = Notification.from_api(payload)
        assert n.actor_id is None
        assert n.actor_name is None
        assert n.project_id is None
        assert n.project_name is None

    def test_non_work_package_resource_yields_no_id(self) -> None:
        payload = notification_payload()
        payload['_links']['resource'] = {'href': '/api/v3/news/7', 'title': 'Something else'}
        n = Notification.from_api(payload)
        assert n.work_package_id is None
        assert n.work_package_title == 'Something else'


class TestNotificationGroup:
    def _group(self) -> NotificationGroup:
        return NotificationGroup.from_notifications([
            Notification.from_api(notification_payload(
                notif_id=1, reason='responsible', actor_id=16, actor_name='Bea Beispiel',
                activity_id=100, created_at='2026-09-10T08:00:00Z')),
            Notification.from_api(notification_payload(
                notif_id=2, reason='mentioned', actor_id=17, actor_name='Cem Muster',
                activity_id=101, created_at='2026-09-14T10:32:00Z')),
            Notification.from_api(notification_payload(
                notif_id=3, reason='responsible', actor_id=16, actor_name='Bea Beispiel',
                activity_id=102, created_at='2026-09-12T09:00:00Z')),
        ])

    def test_aggregates_ids_and_metadata(self) -> None:
        g = self._group()
        assert g.work_package_id == 8202
        assert g.title == 'Demo-Deployment'
        assert g.project_name == 'Sample project'
        assert g.notification_ids == [1, 2, 3]
        assert g.activity_ids == [100, 101, 102]
        assert g.count == 3

    def test_reason_counts_and_actors(self) -> None:
        g = self._group()
        assert g.reason_counts == {'responsible': 2, 'mentioned': 1}
        assert g.actors == ['Bea Beispiel', 'Cem Muster']

    def test_latest_and_earliest_timestamps(self) -> None:
        g = self._group()
        assert g.latest == '2026-09-14T10:32:00Z'
        assert g.earliest == '2026-09-10T08:00:00Z'

    def test_mentioned_flag(self) -> None:
        assert self._group().is_mentioned is True

    def test_empty_notifications_rejected(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            NotificationGroup.from_notifications([])
