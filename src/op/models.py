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
    member_ids: list[int] = Field(default_factory=list)

    @classmethod
    def from_api(cls, payload: dict[str, T.Any]) -> Group:
        links = payload.get('_links') or {}
        members = links.get('members') or []
        member_ids = [
            id_from_href(m.get('href'))
            for m in members
            if isinstance(m, dict)
        ]
        return cls(
            id=payload['id'],
            name=payload['name'],
            member_ids=[m for m in member_ids if m is not None],
        )


class Role(_ApiModel):
    id: int
    name: str

    @classmethod
    def from_api(cls, payload: dict[str, T.Any]) -> Role:
        return cls(id=payload['id'], name=payload['name'])


class Membership(_ApiModel):
    """A project membership: which principal (user or group) holds which roles."""

    id: int
    project_id: int | None = None
    principal_id: int | None = None
    principal_name: str | None = None
    principal_type: str = 'user'  # 'user' | 'group'
    role_ids: list[int] = Field(default_factory=list)
    role_names: list[str] = Field(default_factory=list)

    @classmethod
    def from_api(cls, payload: dict[str, T.Any]) -> Membership:
        links = payload.get('_links') or {}
        principal = links.get('principal') or {}
        href = principal.get('href') or ''
        principal_type = 'group' if '/groups/' in href else 'user'
        roles = [r for r in links.get('roles', []) if isinstance(r, dict)]
        return cls(
            id=payload['id'],
            project_id=_link_id(links, 'project'),
            principal_id=id_from_href(href),
            principal_name=principal.get('title'),
            principal_type=principal_type,
            role_ids=[rid for rid in (id_from_href(r.get('href')) for r in roles) if rid is not None],
            role_names=[r.get('title') for r in roles if r.get('title')],
        )


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
    allowed_options: dict[int, str] = Field(default_factory=dict)

    @property
    def is_multi(self) -> bool:
        """True for multi-value CFs — OpenProject prefixes those types with '[]'."""
        return self.field_format.strip().startswith('[]')

    @classmethod
    def from_api(cls, payload: dict[str, T.Any]) -> CustomField:
        allowed_users: dict[int, str] = {}
        allowed_options: dict[int, str] = {}
        # Prefer _embedded.allowedValues — full objects with _type distinguishing CustomOption vs User
        embedded = payload.get('_embedded') or {}
        for av in embedded.get('allowedValues') or []:
            av_id = av.get('id')
            if av_id is None:
                continue
            if av.get('_type') == 'CustomOption':
                value = av.get('value')
                if value is not None:
                    allowed_options[int(av_id)] = str(value)
            else:
                uname = av.get('name')
                if uname is not None:
                    allowed_users[int(av_id)] = str(uname)
        # Fall back to _links.allowedValues — HAL links; distinguish by href prefix
        if not allowed_users and not allowed_options:
            links = payload.get('_links') or {}
            for av in links.get('allowedValues') or []:
                if not isinstance(av, dict):
                    continue
                href = av.get('href') or ''
                av_id = id_from_href(href)
                title = av.get('title')
                if av_id is None or title is None:
                    continue
                if '/custom_options/' in href:
                    allowed_options[av_id] = str(title)
                else:
                    allowed_users[av_id] = str(title)
        return cls(
            id=payload['id'],
            name=payload['name'],
            field_format=payload.get('fieldFormat') or payload.get('field_format', ''),
            allowed_users=allowed_users,
            allowed_options=allowed_options,
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
    parent_id: int | None = None
    lock_version: int
    custom_fields: dict[str, T.Any] = Field(default_factory=dict)
    custom_field_links: dict[int, int | None] = Field(default_factory=dict)
    custom_field_multi_links: dict[int, list[int]] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, T.Any]) -> WorkPackage:
        links = payload.get('_links', {})
        description_raw = (payload.get('description') or {}).get('raw')
        description = description_raw if description_raw else None

        custom_fields = {k: v for k, v in payload.items() if k.startswith('customField')}

        custom_field_links: dict[int, int | None] = {}
        custom_field_multi_links: dict[int, list[int]] = {}
        for link_key, link_val in links.items():
            m = _CUSTOM_FIELD_KEY_RE.match(link_key)
            if not m:
                continue
            cf_id = int(m.group(1))
            if isinstance(link_val, dict):
                custom_field_links[cf_id] = id_from_href(link_val.get('href'))
            elif isinstance(link_val, list):
                ids = [
                    id_from_href(item.get('href'))
                    for item in link_val
                    if isinstance(item, dict)
                ]
                custom_field_multi_links[cf_id] = [i for i in ids if i is not None]

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
            parent_id=_link_id(links, 'parent'),
            lock_version=payload['lockVersion'],
            custom_fields=custom_fields,
            custom_field_links=custom_field_links,
            custom_field_multi_links=custom_field_multi_links,
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
