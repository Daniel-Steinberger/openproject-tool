from __future__ import annotations

import asyncio
import json
import math
import re
import typing as T
from datetime import date, timedelta

import httpx

from op.models import (
    Activity,
    CustomField,
    Group,
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
_SCHEMA_PAIR_RE = re.compile(r'/schemas/(\d+)-(\d+)$')
_SCHEMA_PAIR_BATCH = 200  # keep URL below ~4 KB
# CustomOption field formats whose options are not returned by the schema endpoint
# but ARE returned by the work-package form endpoint.
_LIST_CF_FORMATS = frozenset({'customoption', '[]customoption'})


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

    async def get_groups(self) -> list[Group]:
        elements = await self._get_collection('/groups')
        return [Group.from_api(e) for e in elements]

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
        # Track one representative (project_id, type_id) per CF for follow-up form calls.
        cf_representative: dict[int, tuple[int, int]] = {}
        for elements in responses:
            for schema in elements:
                self_href = (schema.get('_links') or {}).get('self', {}).get('href', '')
                pair_match = _SCHEMA_PAIR_RE.search(self_href)
                for key, value in schema.items():
                    match = _CUSTOM_FIELD_KEY.match(key)
                    if not match or not isinstance(value, dict):
                        continue
                    field_id = int(match.group(1))
                    if field_id in seen:
                        continue
                    seen[field_id] = CustomField.from_api({
                        'id': field_id,
                        'name': value.get('name', f'Custom Field {field_id}'),
                        'field_format': str(value.get('type', '')).lower(),
                        '_embedded': value.get('_embedded') or {},
                        '_links': value.get('_links') or {},
                    })
                    if pair_match:
                        cf_representative[field_id] = (
                            int(pair_match.group(1)),
                            int(pair_match.group(2)),
                        )
        # List-type CFs often return no inline allowedValues from the schema endpoint.
        # Fetch them via the project form endpoint which always embeds them.
        list_cfs = [
            (cf_id, cf_representative[cf_id])
            for cf_id, cf in seen.items()
            if cf.field_format in _LIST_CF_FORMATS
            and not cf.allowed_options
            and cf_id in cf_representative
        ]
        if list_cfs:
            await self._enrich_list_cf_options(seen, list_cfs)
        return [seen[k] for k in sorted(seen)]

    async def _enrich_list_cf_options(
        self,
        seen: dict[int, CustomField],
        cfs: list[tuple[int, tuple[int, int]]],
    ) -> None:
        """Fetch allowed options for list CFs via the work-package form endpoint."""
        pair_to_cf_ids: dict[tuple[int, int], list[int]] = {}
        for cf_id, pair in cfs:
            pair_to_cf_ids.setdefault(pair, []).append(cf_id)
        pairs = list(pair_to_cf_ids.keys())
        results = await asyncio.gather(
            *(self._fetch_form_schema(p, t) for p, t in pairs),
            return_exceptions=True,
        )
        for (p, t), form_schema in zip(pairs, results):
            if isinstance(form_schema, Exception):
                continue
            for key, value in form_schema.items():
                m = _CUSTOM_FIELD_KEY.match(key)
                if not m or not isinstance(value, dict):
                    continue
                cf_id = int(m.group(1))
                if cf_id not in seen:
                    continue
                for av in (value.get('_embedded') or {}).get('allowedValues') or []:
                    if av.get('_type') == 'CustomOption':
                        opt_id = av.get('id')
                        opt_value = av.get('value')
                        if opt_id is not None and opt_value is not None:
                            seen[cf_id].allowed_options[int(opt_id)] = str(opt_value)

    async def _fetch_form_schema(self, project_id: int, type_id: int) -> dict[str, T.Any]:
        """POST to the work-package form for one project-type pair; returns its embedded schema."""
        data = await self._request(
            'POST',
            f'/projects/{project_id}/work_packages/form',
            json={'_links': {'type': {'href': f'/api/v3/types/{type_id}'}}},
        )
        return data.get('_embedded', {}).get('schema', {})

    async def _fetch_schema_batch(self, pairs: list[str]) -> list[dict[str, T.Any]]:
        filters = [{'id': {'operator': '=', 'values': pairs}}]
        params = [
            ('filters', json.dumps(filters)),
            ('pageSize', str(_DEFAULT_PAGE_SIZE)),
            ('embed[]', 'allowedValues'),
        ]
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

    async def get_busy_days(self, principal_id: int) -> set[date]:
        """Return the set of days an assignee (user or group) already has open tasks on.

        Tasks without a start date contribute nothing. Tasks with only a start date
        contribute that one day; tasks with both start and due contribute the full range.
        """
        filters = [
            {'assigned_to_id': {'operator': '=', 'values': [str(principal_id)]}},
            {'status': {'operator': 'o'}},
        ]
        work_packages = await self.search_work_packages(filters=filters)
        busy: set[date] = set()
        for wp in work_packages:
            if wp.start_date is None:
                continue
            end = wp.due_date or wp.start_date
            current = wp.start_date
            while current <= end:
                busy.add(current)
                current += timedelta(days=1)
        return busy

    async def add_comment(self, wp_id: int, text: str) -> None:
        await self._request(
            'POST',
            f'/work_packages/{wp_id}/activities',
            json={'comment': {'raw': text}},
        )

    async def get_watchers(self, wp_id: int) -> list[User]:
        elements = await self._get_collection(f'/work_packages/{wp_id}/watchers')
        return [User.from_api(e) for e in elements]

    async def add_watcher(self, wp_id: int, user_id: int) -> None:
        await self._request(
            'POST',
            f'/work_packages/{wp_id}/watchers',
            json={'user': {'href': f'/api/v3/users/{user_id}'}},
        )

    async def remove_watcher(self, wp_id: int, user_id: int) -> None:
        path = f'/work_packages/{wp_id}/watchers/{user_id}'
        resp = await self._raw_request('DELETE', path)
        if resp.status_code not in (204, 404):
            self._raise_for_status(resp, 'DELETE', path)

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
