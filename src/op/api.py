from __future__ import annotations

import asyncio
import json
import math
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

    async def get_custom_fields(self) -> list[CustomField]:
        elements = await self._get_collection('/custom_fields')
        return [CustomField.from_api(e) for e in elements]

    # --- work packages ----------------------------------------------------

    async def get_work_package(self, wp_id: int) -> WorkPackage | None:
        response = await self._raw_request('GET', f'/work_packages/{wp_id}')
        if response.status_code == 404:
            return None
        self._raise_for_status(response)
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
        self._raise_for_status(response)
        return response.json()

    async def _raw_request(self, method: str, path: str, **kwargs: T.Any) -> httpx.Response:
        if self._http is None:
            raise OpenProjectError('Client not opened — use `async with OpenProjectClient(...)`')
        return await self._http.request(method, f'{_API_BASE}{path}', **kwargs)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code == 401:
            raise AuthError('Authentication failed — check OP_API_KEY or config api_key')
        if response.status_code >= 400:
            raise OpenProjectError(
                f'OpenProject API error {response.status_code}: {response.text[:200]}'
            )
