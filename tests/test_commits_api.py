from __future__ import annotations

import json

import httpx
import pytest
import respx

from op.api import OpenProjectClient
from op.models import WorkPackage

BASE_URL = 'https://op.example.com'


@pytest.fixture
def client() -> OpenProjectClient:
    return OpenProjectClient(base_url=BASE_URL, api_key='k')


def _wp_payload(cf_id: int, raw: str) -> dict:
    return {
        '_type': 'WorkPackage', 'id': 1, 'subject': 'S', 'lockVersion': 4,
        f'customField{cf_id}': {'raw': raw, 'html': f'<p>{raw}</p>', 'format': 'markdown'},
        '_links': {
            'type': {'href': '/api/v3/types/1', 'title': 'Task'},
            'status': {'href': '/api/v3/statuses/1', 'title': 'Neu'},
            'project': {'href': '/api/v3/projects/10', 'title': 'P'},
        },
    }


async def test_set_custom_field_text_sends_markdown_patch(
    client: OpenProjectClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.patch(f'{BASE_URL}/api/v3/work_packages/1').mock(
        return_value=httpx.Response(200, json=_wp_payload(44, 'hello'))
    )
    async with client:
        await client.set_custom_field_text(1, lock_version=4, cf_id=44, markdown='hello')
    body = json.loads(route.calls.last.request.content)
    assert body == {'lockVersion': 4, 'customField44': {'raw': 'hello', 'format': 'markdown'}}


def test_workpackage_custom_field_text_reads_raw() -> None:
    wp = WorkPackage.from_api(_wp_payload(44, 'line1\nline2'))
    assert wp.custom_field_text(44) == 'line1\nline2'
    assert wp.custom_field_text(99) == ''
