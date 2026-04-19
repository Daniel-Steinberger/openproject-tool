from __future__ import annotations

from pathlib import Path

import httpx
import respx

from op.actions import load_remote_data
from op.api import OpenProjectClient
from op.config import load_config

BASE_URL = 'https://op.example.com'
API_KEY = 'testkey'


def _collection(elements: list[dict]) -> dict:
    return {'total': len(elements), 'count': len(elements), '_embedded': {'elements': elements}}


class TestLoadRemoteData:
    async def test_writes_all_sections(
        self, tmp_path: Path, respx_mock: respx.MockRouter
    ) -> None:
        config_path = tmp_path / 'config.toml'

        respx_mock.get(f'{BASE_URL}/api/v3/statuses').mock(
            return_value=httpx.Response(
                200,
                json=_collection(
                    [
                        {'_type': 'Status', 'id': 1, 'name': 'Neu'},
                        {'_type': 'Status', 'id': 2, 'name': 'Offen'},
                    ]
                ),
            )
        )
        respx_mock.get(f'{BASE_URL}/api/v3/types').mock(
            return_value=httpx.Response(
                200, json=_collection([{'_type': 'Type', 'id': 1, 'name': 'Task'}])
            )
        )
        respx_mock.get(f'{BASE_URL}/api/v3/priorities').mock(
            return_value=httpx.Response(
                200, json=_collection([{'_type': 'Priority', 'id': 8, 'name': 'Normal'}])
            )
        )
        respx_mock.get(f'{BASE_URL}/api/v3/projects').mock(
            return_value=httpx.Response(
                200,
                json=_collection(
                    [{'_type': 'Project', 'id': 10, 'name': 'Web', 'identifier': 'web'}]
                ),
            )
        )
        respx_mock.get(f'{BASE_URL}/api/v3/users').mock(
            return_value=httpx.Response(
                200,
                json=_collection(
                    [
                        {'_type': 'User', 'id': 5, 'name': 'Max'},
                        {'_type': 'User', 'id': 6, 'name': 'Anna'},
                    ]
                ),
            )
        )
        respx_mock.get(f'{BASE_URL}/api/v3/work_packages/schemas').mock(
            return_value=httpx.Response(
                200,
                json={
                    'total': 1,
                    'count': 1,
                    '_embedded': {
                        'elements': [
                            {
                                '_type': 'Schema',
                                'customField3': {'name': 'Story Points', 'type': 'Integer'},
                            }
                        ]
                    },
                },
            )
        )

        async with OpenProjectClient(BASE_URL, API_KEY) as client:
            await load_remote_data(client, config_path)

        cfg = load_config(config_path)
        assert cfg.remote.statuses == {1: 'Neu', 2: 'Offen'}
        assert cfg.remote.types == {1: 'Task'}
        assert cfg.remote.priorities == {8: 'Normal'}
        assert cfg.remote.projects == {10: 'Web'}
        assert cfg.remote.users == {5: 'Max', 6: 'Anna'}
        assert cfg.remote.custom_fields == {3: 'Story Points'}

    async def test_skips_endpoint_returning_404(
        self, tmp_path: Path, respx_mock: respx.MockRouter
    ) -> None:
        """A missing endpoint (e.g. /work_packages/schemas on older installs) must not abort sync."""
        config_path = tmp_path / 'config.toml'

        respx_mock.get(f'{BASE_URL}/api/v3/statuses').mock(
            return_value=httpx.Response(
                200, json=_collection([{'_type': 'Status', 'id': 1, 'name': 'Neu'}])
            )
        )
        for ep in ('types', 'priorities', 'projects', 'users'):
            respx_mock.get(f'{BASE_URL}/api/v3/{ep}').mock(
                return_value=httpx.Response(200, json=_collection([]))
            )
        # Custom-field schema endpoint returns 404 — must be tolerated
        respx_mock.get(f'{BASE_URL}/api/v3/work_packages/schemas').mock(
            return_value=httpx.Response(
                404,
                json={'_type': 'Error', 'message': 'Not found'},
            )
        )

        async with OpenProjectClient(BASE_URL, API_KEY) as client:
            await load_remote_data(client, config_path)

        cfg = load_config(config_path)
        assert cfg.remote.statuses == {1: 'Neu'}
        assert cfg.remote.custom_fields == {}

    async def test_preserves_existing_connection_and_defaults(
        self, tmp_path: Path, respx_mock: respx.MockRouter
    ) -> None:
        config_path = tmp_path / 'config.toml'
        config_path.write_text(
            '[connection]\n'
            'base_url = "https://keep.me.com"\n'
            'api_key = "keep-me"\n'
            '\n'
            '[defaults]\n'
            'status = ["open"]\n'
            'type = ["Task"]\n'
        )

        for ep in ('statuses', 'types', 'priorities', 'projects', 'users', 'custom_fields'):
            respx_mock.get(f'{BASE_URL}/api/v3/{ep}').mock(
                return_value=httpx.Response(200, json=_collection([]))
            )

        async with OpenProjectClient(BASE_URL, API_KEY) as client:
            await load_remote_data(client, config_path)

        cfg = load_config(config_path)
        assert cfg.connection.base_url == 'https://keep.me.com'
        assert cfg.connection.api_key == 'keep-me'
        assert cfg.defaults.status == ['open']
        assert cfg.defaults.type == ['Task']
