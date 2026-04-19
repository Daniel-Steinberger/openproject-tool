from __future__ import annotations

import base64
import json
import typing as T

import httpx
import pytest
import respx

from op.api import AuthError, OpenProjectClient, OpenProjectError

BASE_URL = 'https://op.example.com'
API_KEY = 'testkey'
EXPECTED_AUTH = 'Basic ' + base64.b64encode(f'apikey:{API_KEY}'.encode()).decode()


@pytest.fixture
def client() -> OpenProjectClient:
    return OpenProjectClient(base_url=BASE_URL, api_key=API_KEY)


def _collection(elements: list[dict[str, T.Any]], total: int | None = None) -> dict[str, T.Any]:
    """OpenProject HAL collection response."""
    return {
        'total': total if total is not None else len(elements),
        'count': len(elements),
        '_embedded': {'elements': elements},
    }


class TestAuth:
    async def test_authorization_header(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.get(f'{BASE_URL}/api/v3/statuses').mock(
            return_value=httpx.Response(200, json=_collection([]))
        )
        async with client:
            await client.get_statuses()
        assert route.calls.last.request.headers['authorization'] == EXPECTED_AUTH

    async def test_401_raises_auth_error(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/statuses').mock(
            return_value=httpx.Response(401, json={'message': 'unauthorized'})
        )
        async with client:
            with pytest.raises(AuthError):
                await client.get_statuses()

    async def test_500_raises_error(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/statuses').mock(
            return_value=httpx.Response(500, text='boom')
        )
        async with client:
            with pytest.raises(OpenProjectError):
                await client.get_statuses()


class TestMetadataEndpoints:
    async def test_get_statuses(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/statuses').mock(
            return_value=httpx.Response(
                200,
                json=_collection(
                    [
                        {'_type': 'Status', 'id': 1, 'name': 'Neu'},
                        {'_type': 'Status', 'id': 2, 'name': 'In Bearbeitung'},
                    ]
                ),
            )
        )
        async with client:
            statuses = await client.get_statuses()
        assert len(statuses) == 2
        assert statuses[0].id == 1
        assert statuses[0].name == 'Neu'

    async def test_get_types(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/types').mock(
            return_value=httpx.Response(
                200,
                json=_collection([{'_type': 'Type', 'id': 1, 'name': 'Task'}]),
            )
        )
        async with client:
            types = await client.get_types()
        assert types[0].name == 'Task'

    async def test_get_priorities(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/priorities').mock(
            return_value=httpx.Response(
                200, json=_collection([{'_type': 'Priority', 'id': 8, 'name': 'Normal'}])
            )
        )
        async with client:
            priorities = await client.get_priorities()
        assert priorities[0].name == 'Normal'

    async def test_get_projects(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/projects').mock(
            return_value=httpx.Response(
                200,
                json=_collection(
                    [{'_type': 'Project', 'id': 10, 'name': 'Web', 'identifier': 'web'}]
                ),
            )
        )
        async with client:
            projects = await client.get_projects()
        assert projects[0].identifier == 'web'

    async def test_get_users(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/users').mock(
            return_value=httpx.Response(
                200, json=_collection([{'_type': 'User', 'id': 5, 'name': 'Max'}])
            )
        )
        async with client:
            users = await client.get_users()
        assert users[0].name == 'Max'

    async def test_get_custom_fields(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/custom_fields').mock(
            return_value=httpx.Response(
                200,
                json=_collection(
                    [{'_type': 'CustomField', 'id': 3, 'name': 'Points', 'fieldFormat': 'int'}]
                ),
            )
        )
        async with client:
            cfs = await client.get_custom_fields()
        assert cfs[0].field_format == 'int'


def _work_package(**overrides: T.Any) -> dict[str, T.Any]:
    base = {
        '_type': 'WorkPackage',
        'id': 1,
        'subject': 'Default',
        'description': {'raw': ''},
        'lockVersion': 1,
        '_links': {
            'type': {'href': '/api/v3/types/1', 'title': 'Task'},
            'status': {'href': '/api/v3/statuses/1', 'title': 'Neu'},
            'project': {'href': '/api/v3/projects/10', 'title': 'Projekt'},
            'author': {'href': '/api/v3/users/7', 'title': 'Dev'},
        },
    }
    base.update(overrides)
    return base


class TestWorkPackages:
    async def test_get_work_package_by_id(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/work_packages/1234').mock(
            return_value=httpx.Response(200, json=_work_package(id=1234, subject='Hallo'))
        )
        async with client:
            wp = await client.get_work_package(1234)
        assert wp.id == 1234
        assert wp.subject == 'Hallo'

    async def test_get_work_package_404_returns_none(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/work_packages/9999').mock(
            return_value=httpx.Response(404, json={'message': 'not found'})
        )
        async with client:
            wp = await client.get_work_package(9999)
        assert wp is None

    async def test_search_single_page(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get(f'{BASE_URL}/api/v3/work_packages').mock(
            return_value=httpx.Response(
                200, json=_collection([_work_package(id=1), _work_package(id=2)])
            )
        )
        async with client:
            results = await client.search_work_packages()
        assert [wp.id for wp in results] == [1, 2]

    async def test_search_sends_filters_as_json(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.get(f'{BASE_URL}/api/v3/work_packages').mock(
            return_value=httpx.Response(200, json=_collection([]))
        )
        async with client:
            await client.search_work_packages(
                filters=[
                    {'status_id': {'operator': '=', 'values': ['1', '2']}},
                    {'type_id': {'operator': '=', 'values': ['5']}},
                ]
            )
        sent_filters = json.loads(route.calls.last.request.url.params['filters'])
        assert sent_filters == [
            {'status_id': {'operator': '=', 'values': ['1', '2']}},
            {'type_id': {'operator': '=', 'values': ['5']}},
        ]

    async def test_search_paginates_parallel(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        """With total=250 and pageSize=100, expect 3 pages (offsets 1, 2, 3 in OpenProject)."""
        pages = {
            '1': _collection([_work_package(id=i) for i in range(1, 101)], total=250),
            '2': _collection([_work_package(id=i) for i in range(101, 201)], total=250),
            '3': _collection([_work_package(id=i) for i in range(201, 251)], total=250),
        }

        def responder(request: httpx.Request) -> httpx.Response:
            offset = request.url.params.get('offset', '1')
            return httpx.Response(200, json=pages[offset])

        respx_mock.get(f'{BASE_URL}/api/v3/work_packages').mock(side_effect=responder)

        async with client:
            results = await client.search_work_packages(page_size=100)
        assert len(results) == 250
        assert results[0].id == 1
        assert results[-1].id == 250

    async def test_update_work_package_sends_patch_with_lock_version(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.patch(f'{BASE_URL}/api/v3/work_packages/1234').mock(
            return_value=httpx.Response(
                200, json=_work_package(id=1234, subject='neu', lockVersion=4)
            )
        )
        async with client:
            updated = await client.update_work_package(
                1234, lock_version=3, changes={'subject': 'neu'}
            )
        body = json.loads(route.calls.last.request.content)
        assert body == {'lockVersion': 3, 'subject': 'neu'}
        assert updated.id == 1234

    async def test_add_comment(
        self, client: OpenProjectClient, respx_mock: respx.MockRouter
    ) -> None:
        route = respx_mock.post(f'{BASE_URL}/api/v3/work_packages/1234/activities').mock(
            return_value=httpx.Response(201, json={'id': 77})
        )
        async with client:
            await client.add_comment(1234, 'Hallo Welt')
        body = json.loads(route.calls.last.request.content)
        assert body == {'comment': {'raw': 'Hallo Welt'}}


class TestClientLifecycle:
    async def test_client_is_closed_after_context(self) -> None:
        client = OpenProjectClient(base_url=BASE_URL, api_key=API_KEY)
        async with client:
            assert client.is_open
        assert not client.is_open
