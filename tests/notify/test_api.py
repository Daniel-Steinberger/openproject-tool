from __future__ import annotations

import json
import typing as T

import httpx
import pytest
import respx

from op.api import OpenProjectError
from op.notify.api import NotificationsClient

from .test_models import notification_payload

BASE_URL = 'https://op.example.com'
API_KEY = 'testkey'


@pytest.fixture
def client() -> NotificationsClient:
    return NotificationsClient(base_url=BASE_URL, api_key=API_KEY)


def _collection(
    elements: list[dict[str, T.Any]],
    *,
    total: int | None = None,
    next_href: str | None = None,
) -> dict[str, T.Any]:
    links: dict[str, T.Any] = {'self': {'href': '/api/v3/notifications'}}
    if next_href:
        links['nextByOffset'] = {'href': next_href}
    return {
        'total': total if total is not None else len(elements),
        'count': len(elements),
        '_embedded': {'elements': elements},
        '_links': links,
    }


class TestGetUnreadNotifications:
    async def test_filters_for_unread(
        self, client: NotificationsClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.get(f'{BASE_URL}/api/v3/notifications').mock(
            return_value=httpx.Response(200, json=_collection([notification_payload()]))
        )
        async with client:
            result = await client.get_unread_notifications()
        assert [n.id for n in result] == [1]
        filters = json.loads(route.calls.last.request.url.params['filters'])
        assert filters == [{'readIAN': {'operator': '=', 'values': ['f']}}]
        assert route.calls.last.request.url.params['pageSize'] == '100'

    async def test_follows_next_by_offset(
        self, client: NotificationsClient, respx_mock: respx.MockRouter
    ) -> None:
        page2 = '/api/v3/notifications?offset=2&pageSize=100'
        respx_mock.get(f'{BASE_URL}/api/v3/notifications', params={'offset': '2'}).mock(
            return_value=httpx.Response(200, json=_collection([notification_payload(notif_id=2)]))
        )
        respx_mock.get(f'{BASE_URL}/api/v3/notifications').mock(
            return_value=httpx.Response(
                200,
                json=_collection([notification_payload(notif_id=1)], total=2, next_href=page2),
            )
        )
        async with client:
            result = await client.get_unread_notifications()
        assert [n.id for n in result] == [1, 2]

    async def test_stops_on_repeated_next_link(
        self, client: NotificationsClient, respx_mock: respx.MockRouter
    ) -> None:
        """A server that keeps handing out the same next link must not loop forever."""
        same = '/api/v3/notifications?offset=2&pageSize=100'
        respx_mock.get(f'{BASE_URL}/api/v3/notifications').mock(
            return_value=httpx.Response(
                200,
                json=_collection([notification_payload(notif_id=1)], total=99, next_href=same),
            )
        )
        async with client:
            result = await client.get_unread_notifications()
        assert [n.id for n in result] == [1, 1]  # first page + one follow-up, then stop

    async def test_empty_inbox(
        self, client: NotificationsClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/notifications').mock(
            return_value=httpx.Response(200, json=_collection([]))
        )
        async with client:
            assert await client.get_unread_notifications() == []


class TestMarkRead:
    async def test_posts_to_read_ian_endpoint(
        self, client: NotificationsClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.post(f'{BASE_URL}/api/v3/notifications/42/read_ian').mock(
            return_value=httpx.Response(204)
        )
        async with client:
            await client.mark_read(42)
        assert route.called

    async def test_accepts_already_read_404_as_success(
        self, client: NotificationsClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.post(f'{BASE_URL}/api/v3/notifications/42/read_ian').mock(
            return_value=httpx.Response(404, json={'_type': 'Error', 'message': 'not found'})
        )
        async with client:
            await client.mark_read(42)  # must not raise

    async def test_raises_on_server_error(
        self, client: NotificationsClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.post(f'{BASE_URL}/api/v3/notifications/42/read_ian').mock(
            return_value=httpx.Response(500, text='boom')
        )
        async with client:
            with pytest.raises(OpenProjectError):
                await client.mark_read(42)


class TestActivityDetails:
    async def test_activities_expose_field_changes(
        self, client: NotificationsClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/work_packages/8202/activities').mock(
            return_value=httpx.Response(200, json=_collection([{
                '_type': 'Activity::Comment',
                'id': 110445,
                'comment': {'raw': 'Kurzer Kommentar'},
                'details': [
                    {'raw': 'Status geändert von **Neu** zu **In Bearbeitung**'},
                    {'raw': 'Zugewiesen an wurde auf **Bea Beispiel** gesetzt'},
                ],
                'createdAt': '2026-09-14T10:32:00Z',
                '_links': {'user': {'href': '/api/v3/users/16', 'title': 'Bea Beispiel'}},
            }])),
        )
        async with client:
            activities = await client.get_activities(8202)
        assert activities[0].details == [
            'Status geändert von **Neu** zu **In Bearbeitung**',
            'Zugewiesen an wurde auf **Bea Beispiel** gesetzt',
        ]
        assert activities[0].comment == 'Kurzer Kommentar'


class TestWorkPackageResponsible:
    async def test_responsible_is_parsed(
        self, client: NotificationsClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/work_packages/8202').mock(
            return_value=httpx.Response(200, json={
                'id': 8202,
                'subject': 'Demo-Deployment',
                'lockVersion': 3,
                '_links': {
                    'type': {'href': '/api/v3/types/1', 'title': 'Task'},
                    'status': {'href': '/api/v3/statuses/7', 'title': 'In Bearbeitung'},
                    'project': {'href': '/api/v3/projects/106', 'title': 'Sample project'},
                    'assignee': {'href': '/api/v3/users/16', 'title': 'Bea Beispiel'},
                    'responsible': {'href': '/api/v3/users/7', 'title': 'Dana Muster'},
                },
            }),
        )
        async with client:
            wp = await client.get_work_package(8202)
        assert wp is not None
        assert wp.responsible_id == 7
        assert wp.responsible_name == 'Dana Muster'


class TestGetMe:
    async def test_returns_id_and_display_name(
        self, client: NotificationsClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/users/me').mock(
            return_value=httpx.Response(200, json={
                'id': 7, 'firstName': 'Dana', 'lastName': 'Muster',
                'name': 'Dana Muster', 'login': 'dana',
            })
        )
        async with client:
            user_id, name = await client.get_me()
        assert user_id == 7
        assert name == 'Dana Muster'
