"""OpenProject API access for the notification inbox.

Extends `OpenProjectClient` rather than wrapping it: authentication, error
translation and the request plumbing are identical, only the endpoints differ.
"""

from __future__ import annotations

import json
import typing as T

from op.api import _API_BASE, OpenProjectClient
from op.notify.models import Notification

# The server caps page size at 100 for this collection and ignores larger values.
_PAGE_SIZE = 100
# Guard against a server that keeps handing out the same "next" link.
_MAX_PAGES = 100


def _api_path(href: str) -> str:
    """Turn a HAL href (`/api/v3/notifications?…`) into a client path (`/notifications?…`)."""
    return href[len(_API_BASE):] if href.startswith(_API_BASE) else href


class NotificationsClient(OpenProjectClient):
    async def get_notifications(self, *, read: bool | None = False) -> list[Notification]:
        """Notifications of the authenticated user (the inbox is always personal).

        `read=False` returns the unread ones, `read=True` the read ones, `None`
        everything. Pagination follows `_links.nextByOffset` — computing offsets
        ourselves is unreliable here, the server decides how far it goes.
        """
        params: dict[str, str] = {'pageSize': str(_PAGE_SIZE)}
        if read is not None:
            params['filters'] = json.dumps(
                [{'readIAN': {'operator': '=', 'values': ['t' if read else 'f']}}]
            )
        data = await self._request('GET', '/notifications', params=params)
        elements = list(data['_embedded']['elements'])

        seen: set[str] = set()
        for _ in range(_MAX_PAGES):
            next_href = self._next_href(data)
            if not next_href or next_href in seen:
                break
            seen.add(next_href)
            data = await self._request('GET', _api_path(next_href))
            elements.extend(data['_embedded']['elements'])

        return [Notification.from_api(e) for e in elements]

    async def get_unread_notifications(self) -> list[Notification]:
        return await self.get_notifications(read=False)

    async def get_me(self) -> tuple[int, str]:
        """Id and display name of the authenticated user — the inbox owner."""
        data = await self._request('GET', '/users/me')
        name = data.get('name') or ' '.join(
            part for part in (data.get('firstName'), data.get('lastName')) if part
        )
        return int(data['id']), name or data.get('login') or f"#{data['id']}"

    async def mark_read(self, notification: int | Notification) -> None:
        """Mark one notification as read.

        A 404 counts as success: the notification is already gone, which is the
        state we wanted. There is no documented bulk endpoint, so callers that
        clear many notifications simply call this repeatedly.
        """
        if isinstance(notification, Notification):
            path = _api_path(notification.read_href or '')
        else:
            path = f'/notifications/{notification}/read_ian'
        # A bare POST is refused with 406 "Missing content-type header" — the
        # endpoint takes no body, but it insists on being told what isn't there.
        response = await self._raw_request(
            'POST', path, headers={'Content-Type': 'application/json'}
        )
        if response.status_code == 404:
            return
        self._raise_for_status(response, 'POST', path)

    @staticmethod
    def _next_href(data: dict[str, T.Any]) -> str | None:
        link = (data.get('_links') or {}).get('nextByOffset')
        return link.get('href') if isinstance(link, dict) else None
