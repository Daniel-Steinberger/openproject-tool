from __future__ import annotations

import re
import typing as T
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

_ID_RE = re.compile(r'/(\d+)/?$')
_CUSTOM_FIELD_KEY_RE = re.compile(r'^customField(\d+)$')


def id_from_href(href: str | None) -> int | None:
    """Extract the trailing numeric ID from an OpenProject HAL link (e.g. `/api/v3/users/5`)."""
    if not href:
        return None
    match = _ID_RE.search(href)
    return int(match.group(1)) if match else None


class _ApiModel(BaseModel):
    model_config = ConfigDict(frozen=False, extra='ignore')


class Status(_ApiModel):
    id: int
    name: str

    @classmethod
    def from_api(cls, payload: dict[str, T.Any]) -> Status:
        return cls(id=payload['id'], name=payload['name'])


class WorkPackageType(_ApiModel):
    id: int
    name: str

    @classmethod
    def from_api(cls, payload: dict[str, T.Any]) -> WorkPackageType:
        return cls(id=payload['id'], name=payload['name'])


class Priority(_ApiModel):
    id: int
    name: str

    @classmethod
    def from_api(cls, payload: dict[str, T.Any]) -> Priority:
        return cls(id=payload['id'], name=payload['name'])


class Project(_ApiModel):
    id: int
    name: str
    identifier: str | None = None
    parent_id: int | None = None

    @classmethod
    def from_api(cls, payload: dict[str, T.Any]) -> Project:
        links = payload.get('_links') or {}
        return cls(
            id=payload['id'],
            name=payload['name'],
            identifier=payload.get('identifier'),
            parent_id=_link_id(links, 'parent'),
        )


class User(_ApiModel):
    id: int
    name: str
    login: str | None = None
    email: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, T.Any]) -> User:
        return cls(
            id=payload['id'],
            name=payload['name'],
            login=payload.get('login'),
            email=payload.get('email'),
        )


class Group(_ApiModel):
    id: int
    name: str

    @classmethod
    def from_api(cls, payload: dict[str, T.Any]) -> Group:
        return cls(id=payload['id'], name=payload['name'])


class Activity(_ApiModel):
    id: int
    comment: str | None = None
    comment_html: str | None = None
    user_name: str | None = None
    user_id: int | None = None
    created_at: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, T.Any]) -> Activity:
        comment_payload = payload.get('comment') or {}
        comment_raw = comment_payload.get('raw') or None
        comment_html = comment_payload.get('html') or None
        links = payload.get('_links', {})
        return cls(
            id=payload['id'],
            comment=comment_raw,
            comment_html=comment_html,
            user_name=_link_title(links, 'user'),
            user_id=_link_id(links, 'user'),
            created_at=payload.get('createdAt'),
        )


class CustomField(_ApiModel):
    id: int
    name: str
    field_format: str
    allowed_users: dict[int, str] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, T.Any]) -> CustomField:
        allowed_users: dict[int, str] = {}
        # Prefer _embedded.allowedValues (full User objects with id+name)
        embedded = payload.get('_embedded') or {}
        for av in embedded.get('allowedValues') or []:
            uid = av.get('id')
            uname = av.get('name')
            if uid is not None and uname is not None:
                allowed_users[int(uid)] = str(uname)
        # Fall back to _links.allowedValues (HAL links with href+title)
        if not allowed_users:
            links = payload.get('_links') or {}
            for av in links.get('allowedValues') or []:
                if isinstance(av, dict):
                    uid = id_from_href(av.get('href'))
                    uname = av.get('title')
                    if uid is not None and uname is not None:
                        allowed_users[uid] = str(uname)
        return cls(
            id=payload['id'],
            name=payload['name'],
            field_format=payload.get('fieldFormat') or payload.get('field_format', ''),
            allowed_users=allowed_users,
        )


class WorkPackage(_ApiModel):
    id: int
    subject: str
    description: str | None = None
    type_id: int
    type_name: str
    status_id: int
    status_name: str
    project_id: int
    project_name: str
    priority_id: int | None = None
    priority_name: str | None = None
    assignee_id: int | None = None
    assignee_name: str | None = None
    author_id: int | None = None
    author_name: str | None = None
    start_date: date | None = None
    due_date: date | None = None
    lock_version: int
    custom_fields: dict[str, T.Any] = Field(default_factory=dict)
    custom_field_links: dict[int, int | None] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, T.Any]) -> WorkPackage:
        links = payload.get('_links', {})
        description_raw = (payload.get('description') or {}).get('raw')
        description = description_raw if description_raw else None

        custom_fields = {k: v for k, v in payload.items() if k.startswith('customField')}

        custom_field_links: dict[int, int | None] = {}
        for link_key, link_val in links.items():
            m = _CUSTOM_FIELD_KEY_RE.match(link_key)
            if m and isinstance(link_val, dict):
                cf_id = int(m.group(1))
                custom_field_links[cf_id] = id_from_href(link_val.get('href'))

        return cls(
            id=payload['id'],
            subject=payload['subject'],
            description=description,
            type_id=_link_id(links, 'type') or 0,
            type_name=_link_title(links, 'type') or '',
            status_id=_link_id(links, 'status') or 0,
            status_name=_link_title(links, 'status') or '',
            project_id=_link_id(links, 'project') or 0,
            project_name=_link_title(links, 'project') or '',
            priority_id=_link_id(links, 'priority'),
            priority_name=_link_title(links, 'priority'),
            assignee_id=_link_id(links, 'assignee'),
            assignee_name=_link_title(links, 'assignee'),
            author_id=_link_id(links, 'author'),
            author_name=_link_title(links, 'author'),
            start_date=_parse_date(payload.get('startDate')),
            due_date=_parse_date(payload.get('dueDate')),
            lock_version=payload['lockVersion'],
            custom_fields=custom_fields,
            custom_field_links=custom_field_links,
        )


def _link_id(links: dict[str, T.Any], key: str) -> int | None:
    link = links.get(key) or {}
    return id_from_href(link.get('href'))


def _link_title(links: dict[str, T.Any], key: str) -> str | None:
    link = links.get(key) or {}
    if not link.get('href'):
        return None
    return link.get('title')


def _parse_date(value: T.Any) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)
