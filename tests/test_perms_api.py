from __future__ import annotations

import json
import typing as T

import httpx
import pytest
import respx

from op.api import OpenProjectClient

BASE_URL = 'https://op.example.com'
API_KEY = 'testkey'


@pytest.fixture
def client() -> OpenProjectClient:
    return OpenProjectClient(base_url=BASE_URL, api_key=API_KEY)


def _collection(elements: list[dict[str, T.Any]], total: int | None = None) -> dict[str, T.Any]:
    return {
        'total': total if total is not None else len(elements),
        'count': len(elements),
        '_embedded': {'elements': elements},
    }


def _membership(mid: int, principal_href: str, name: str, role_ids: list[int]) -> dict[str, T.Any]:
    return {
        '_type': 'Membership', 'id': mid,
        '_links': {
            'project': {'href': '/api/v3/projects/106', 'title': 'StBVS'},
            'principal': {'href': principal_href, 'title': name},
            'roles': [{'href': f'/api/v3/roles/{r}', 'title': 'Member'} for r in role_ids],
        },
    }


class TestRoles:
    async def test_get_roles(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/roles').mock(
            return_value=httpx.Response(200, json=_collection([
                {'_type': 'Role', 'id': 3, 'name': 'Member'},
                {'_type': 'Role', 'id': 5, 'name': 'Project admin'},
            ]))
        )
        async with client:
            roles = await client.get_roles()
        assert [(r.id, r.name) for r in roles] == [(3, 'Member'), (5, 'Project admin')]


class TestMemberships:
    async def test_get_memberships_filters_by_project(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.get(f'{BASE_URL}/api/v3/memberships').mock(
            return_value=httpx.Response(200, json=_collection([
                _membership(2877, '/api/v3/groups/6', 'KB', [3]),
                _membership(2879, '/api/v3/users/33', 'Grit Keiwel', [3]),
            ]))
        )
        async with client:
            ms = await client.get_memberships(106)
        sent = json.loads(route.calls.last.request.url.params['filters'])
        assert sent == [{'project': {'operator': '=', 'values': ['106']}}]
        assert [(m.principal_type, m.principal_id) for m in ms] == [('group', 6), ('user', 33)]

    async def test_get_principal_memberships_filters_by_principal(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.get(f'{BASE_URL}/api/v3/memberships').mock(
            return_value=httpx.Response(200, json=_collection([
                _membership(1, '/api/v3/groups/6', 'KB', [3]),
            ]))
        )
        async with client:
            ms = await client.get_principal_memberships(6)
        sent = json.loads(route.calls.last.request.url.params['filters'])
        assert sent == [{'principal': {'operator': '=', 'values': ['6']}}]
        assert ms[0].principal_id == 6

    async def test_set_group_members_patches_full_list(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.patch(f'{BASE_URL}/api/v3/groups/6').mock(
            return_value=httpx.Response(200, json={
                '_type': 'Group', 'id': 6, 'name': 'KB',
                '_links': {'members': [
                    {'href': '/api/v3/users/33'}, {'href': '/api/v3/users/99'},
                ]},
            })
        )
        async with client:
            g = await client.set_group_members(6, [33, 99])
        body = json.loads(route.calls.last.request.content)
        assert body == {'_links': {'members': [
            {'href': '/api/v3/users/33'}, {'href': '/api/v3/users/99'},
        ]}}
        assert g.member_ids == [33, 99]

    async def test_create_user_sends_fields(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.post(f'{BASE_URL}/api/v3/users').mock(
            return_value=httpx.Response(201, json={
                '_type': 'User', 'id': 200, 'name': 'Neu Person',
                'login': 'neu@dvs.ag', 'email': 'neu@dvs.ag',
                'firstName': 'Neu', 'lastName': 'Person', 'status': 'invited',
            })
        )
        async with client:
            u = await client.create_user(
                login='neu@dvs.ag', email='neu@dvs.ag',
                first_name='Neu', last_name='Person', status='invited',
            )
        body = json.loads(route.calls.last.request.content)
        assert body == {
            'login': 'neu@dvs.ag', 'email': 'neu@dvs.ag',
            'firstName': 'Neu', 'lastName': 'Person', 'status': 'invited',
        }
        assert u.id == 200 and u.status == 'invited'

    async def test_get_group_members(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/groups/6').mock(
            return_value=httpx.Response(200, json={
                '_type': 'Group', 'id': 6, 'name': 'KB',
                '_links': {'members': [
                    {'href': '/api/v3/users/33'}, {'href': '/api/v3/users/34'},
                ]},
            })
        )
        async with client:
            members = await client.get_group_members(6)
        assert members == [33, 34]

    async def test_create_membership_user(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.post(f'{BASE_URL}/api/v3/memberships').mock(
            return_value=httpx.Response(201, json=_membership(99, '/api/v3/users/33', 'Grit', [3]))
        )
        async with client:
            m = await client.create_membership(106, 33, [3])
        body = json.loads(route.calls.last.request.content)
        assert body == {'_links': {
            'project': {'href': '/api/v3/projects/106'},
            'principal': {'href': '/api/v3/users/33'},
            'roles': [{'href': '/api/v3/roles/3'}],
        }}
        assert m.principal_id == 33

    async def test_create_membership_group_uses_groups_href(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.post(f'{BASE_URL}/api/v3/memberships').mock(
            return_value=httpx.Response(201, json=_membership(98, '/api/v3/groups/6', 'KB', [3]))
        )
        async with client:
            await client.create_membership(106, 6, [3], principal_type='group')
        body = json.loads(route.calls.last.request.content)
        assert body['_links']['principal'] == {'href': '/api/v3/groups/6'}

    async def test_update_membership_roles(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.patch(f'{BASE_URL}/api/v3/memberships/99').mock(
            return_value=httpx.Response(200, json=_membership(99, '/api/v3/users/33', 'Grit', [3, 5]))
        )
        async with client:
            m = await client.update_membership_roles(99, [3, 5])
        body = json.loads(route.calls.last.request.content)
        assert body == {'_links': {'roles': [
            {'href': '/api/v3/roles/3'}, {'href': '/api/v3/roles/5'},
        ]}}
        assert m.role_ids == [3, 5]
