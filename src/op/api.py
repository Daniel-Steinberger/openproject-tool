from __future__ import annotations

import asyncio
import json
import math
import re
import typing as T

import httpx

from op.models import (
    Activity,
    CustomField,
    Priority,
    Project,
    Status,
    User,
    WorkPackage,
    WorkPackageType,
)

_API_BASE = '/api/v3'
_DEFAULT_PAGE_SIZE = 100
_CUSTOM_FIELD_KEY = re.compile(r'^customField(\d+)$')
_SCHEMA_PAIR_BATCH = 200  # keep URL below ~4 KB


class OpenProjectError(Exception):
    """Base exception for API errors."""


class AuthError(OpenProjectError):
    """Raised when the API rejects our credentials (HTTP 401)."""


class OpenProjectClient:
    """Async HTTP client for OpenProject API v3."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip('/')
        self._api_key = api_key
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None

    @property
    def is_open(self) -> bool:
        return self._http is not None

    async def __aenter__(self) -> OpenProjectClient:
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            auth=('apikey', self._api_key),
            timeout=self._timeout,
        )
        return self

    async def __aexit__(self, *_: T.Any) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # --- metadata ---------------------------------------------------------

    async def get_statuses(self) -> list[Status]:
        elements = await self._get_collection('/statuses')
        return [Status.from_api(e) for e in elements]

    async def get_types(self) -> list[WorkPackageType]:
        elements = await self._get_collection('/types')
        return [WorkPackageType.from_api(e) for e in elements]

    async def get_priorities(self) -> list[Priority]:
        elements = await self._get_collection('/priorities')
        return [Priority.from_api(e) for e in elements]

    async def get_projects(self) -> list[Project]:
        elements = await self._get_collection('/projects')
        return [Project.from_api(e) for e in elements]

    async def get_users(self) -> list[User]:
        elements = await self._get_collection('/users')
        return [User.from_api(e) for e in elements]

    async def get_custom_fields(
        self, *, project_ids: list[int], type_ids: list[int]
    ) -> list[CustomField]:
        """Derive custom-field definitions from /work_packages/schemas.

        The schemas endpoint is mandatory-filtered by `project-id : type-id` pairs, so the caller
        must supply known project and type IDs. Pair lists exceeding `_SCHEMA_PAIR_BATCH` are
        split across multiple parallel requests to stay under typical nginx URL limits.
        When either list is empty, no request is sent and `[]` is returned.
        """
        if not project_ids or not type_ids:
            return []
        pairs = [f'{p}-{t}' for p in project_ids for t in type_ids]
        batches = [
            pairs[i : i + _SCHEMA_PAIR_BATCH]
            for i in range(0, len(pairs), _SCHEMA_PAIR_BATCH)
        ]
        responses = await asyncio.gather(*(self._fetch_schema_batch(b) for b in batches))
        seen: dict[int, CustomField] = {}
        for elements in responses:
            for schema in elements:
                for key, value in schema.items():
                    match = _CUSTOM_FIELD_KEY.match(key)
                    if not match or not isinstance(value, dict):
                        continue
                    field_id = int(match.group(1))
                    if field_id in seen:
                        continue
                    seen[field_id] = CustomField(
                        id=field_id,
                        name=value.get('name', f'Custom Field {field_id}'),
                        field_format=str(value.get('type', '')).lower(),
                    )
        return [seen[k] for k in sorted(seen)]

    async def _fetch_schema_batch(self, pairs: list[str]) -> list[dict[str, T.Any]]:
        filters = [{'id': {'operator': '=', 'values': pairs}}]
        params = {'filters': json.dumps(filters), 'pageSize': str(_DEFAULT_PAGE_SIZE)}
        data = await self._request('GET', '/work_packages/schemas', params=params)
        return list(data['_embedded']['elements'])

    # --- work packages ----------------------------------------------------

    async def get_work_package(self, wp_id: int) -> WorkPackage | None:
        path = f'/work_packages/{wp_id}'
        response = await self._raw_request('GET', path)
        if response.status_code == 404:
            return None
        self._raise_for_status(response, 'GET', path)
        return WorkPackage.from_api(response.json())

    async def search_work_packages(
        self,
        *,
        filters: list[dict[str, T.Any]] | None = None,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ) -> list[WorkPackage]:
        params = self._search_params(filters=filters, page_size=page_size, offset=1)
        first = await self._request('GET', '/work_packages', params=params)

        elements = list(first['_embedded']['elements'])
        total = first.get('total', len(elements))

        if total <= len(elements):
            return [WorkPackage.from_api(e) for e in elements]

        total_pages = math.ceil(total / page_size)
        extra_pages = await asyncio.gather(
            *(
                self._request(
                    'GET',
                    '/work_packages',
                    params=self._search_params(
                        filters=filters, page_size=page_size, offset=page
                    ),
                )
                for page in range(2, total_pages + 1)
            )
        )
        for page_data in extra_pages:
            elements.extend(page_data['_embedded']['elements'])

        return [WorkPackage.from_api(e) for e in elements]

    async def update_work_package(
        self, wp_id: int, *, lock_version: int, changes: dict[str, T.Any]
    ) -> WorkPackage:
        body = {'lockVersion': lock_version, **changes}
        data = await self._request('PATCH', f'/work_packages/{wp_id}', json=body)
        return WorkPackage.from_api(data)

    async def get_activities(self, wp_id: int) -> list[Activity]:
        elements = await self._get_collection(f'/work_packages/{wp_id}/activities')
        return [Activity.from_api(e) for e in elements]

    async def add_comment(self, wp_id: int, text: str) -> None:
        await self._request(
            'POST',
            f'/work_packages/{wp_id}/activities',
            json={'comment': {'raw': text}},
        )

    # --- internals --------------------------------------------------------

    @staticmethod
    def _search_params(
        *, filters: list[dict[str, T.Any]] | None, page_size: int, offset: int
    ) -> dict[str, str]:
        params = {'pageSize': str(page_size), 'offset': str(offset)}
        if filters:
            params['filters'] = json.dumps(filters)
        return params

    async def _get_collection(self, path: str) -> list[dict[str, T.Any]]:
        data = await self._request('GET', path, params={'pageSize': str(_DEFAULT_PAGE_SIZE)})
        return list(data['_embedded']['elements'])

    async def _request(self, method: str, path: str, **kwargs: T.Any) -> dict[str, T.Any]:
        response = await self._raw_request(method, path, **kwargs)
        self._raise_for_status(response, method, path)
        return response.json()

    async def _raw_request(self, method: str, path: str, **kwargs: T.Any) -> httpx.Response:
        if self._http is None:
            raise OpenProjectError('Client not opened — use `async with OpenProjectClient(...)`')
        return await self._http.request(method, f'{_API_BASE}{path}', **kwargs)

    @staticmethod
    def _raise_for_status(response: httpx.Response, method: str, path: str) -> None:
        if response.status_code == 401:
            raise AuthError(
                f'Authentication failed for {method} {_API_BASE}{path} '
                '— check OP_API_KEY or config api_key'
            )
        if response.status_code >= 400:
            raise OpenProjectError(
                f'{method} {_API_BASE}{path} returned {response.status_code}: '
                f'{response.text[:200]}'
            )
