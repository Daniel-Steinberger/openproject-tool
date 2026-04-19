from __future__ import annotations

import typing as T


class UpdateForm:
    """Pending-changes state for the update dialog.

    Each attribute is `None` (unchanged) or holds the desired new value.
    Call `api_changes()` to obtain the JSON-ready PATCH body for OpenProject.

    Batch edits typically only set link fields (status/type/priority/assignee).
    Single-task edits may additionally set scalar fields (subject/description/dates).
    """

    def __init__(self) -> None:
        self._status_id: int | None = None
        self._type_id: int | None = None
        self._priority_id: int | None = None
        self._assignee_id: int | None = None
        self._assignee_is_group: bool = False
        self._unassign: bool = False
        self._subject: str | None = None
        self._description: str | None = None
        self._start_date: str | None = None
        self._due_date: str | None = None

    # --- link fields -----------------------------------------------------

    @property
    def status_id(self) -> int | None:
        return self._status_id

    @status_id.setter
    def status_id(self, value: int | None) -> None:
        self._status_id = value

    @property
    def type_id(self) -> int | None:
        return self._type_id

    @type_id.setter
    def type_id(self, value: int | None) -> None:
        self._type_id = value

    @property
    def priority_id(self) -> int | None:
        return self._priority_id

    @priority_id.setter
    def priority_id(self, value: int | None) -> None:
        self._priority_id = value

    @property
    def assignee_id(self) -> int | None:
        return self._assignee_id

    @assignee_id.setter
    def assignee_id(self, value: int | None) -> None:
        self._assignee_id = value
        self._assignee_is_group = False
        if value is not None:
            self._unassign = False

    def set_assignee(self, *, principal_id: int, is_group: bool) -> None:
        """Explicitly set an assignee by principal ID and kind (user vs. group)."""
        self._assignee_id = principal_id
        self._assignee_is_group = is_group
        self._unassign = False

    @property
    def unassign(self) -> bool:
        return self._unassign

    @unassign.setter
    def unassign(self, value: bool) -> None:
        self._unassign = value
        if value:
            self._assignee_id = None

    # --- scalar fields ---------------------------------------------------

    @property
    def subject(self) -> str | None:
        return self._subject

    @subject.setter
    def subject(self, value: str | None) -> None:
        self._subject = value or None

    @property
    def description(self) -> str | None:
        return self._description

    @description.setter
    def description(self, value: str | None) -> None:
        self._description = value if value else None

    @property
    def start_date(self) -> str | None:
        return self._start_date

    @start_date.setter
    def start_date(self, value: str | None) -> None:
        self._start_date = value or None

    @property
    def due_date(self) -> str | None:
        return self._due_date

    @due_date.setter
    def due_date(self, value: str | None) -> None:
        self._due_date = value or None

    # --- derived ---------------------------------------------------------

    @property
    def has_changes(self) -> bool:
        return bool(self.api_changes())

    def api_changes(self) -> dict[str, T.Any]:
        changes: dict[str, T.Any] = {}

        links: dict[str, dict[str, T.Any]] = {}
        if self._status_id is not None:
            links['status'] = {'href': f'/api/v3/statuses/{self._status_id}'}
        if self._type_id is not None:
            links['type'] = {'href': f'/api/v3/types/{self._type_id}'}
        if self._priority_id is not None:
            links['priority'] = {'href': f'/api/v3/priorities/{self._priority_id}'}
        if self._assignee_id is not None:
            kind = 'groups' if self._assignee_is_group else 'users'
            links['assignee'] = {'href': f'/api/v3/{kind}/{self._assignee_id}'}
        elif self._unassign:
            links['assignee'] = {'href': None}
        if links:
            changes['_links'] = links

        if self._subject is not None:
            changes['subject'] = self._subject
        if self._description is not None:
            changes['description'] = {'raw': self._description, 'format': 'markdown'}
        if self._start_date is not None:
            changes['startDate'] = self._start_date
        if self._due_date is not None:
            changes['dueDate'] = self._due_date

        return changes

    def summary(
        self,
        *,
        statuses: dict[int, str] | None = None,
        types: dict[int, str] | None = None,
        priorities: dict[int, str] | None = None,
        users: dict[int, str] | None = None,
    ) -> str:
        """Human-readable one-line summary for confirmation display."""
        lines: list[str] = []
        if self._status_id is not None:
            name = (statuses or {}).get(self._status_id, f'#{self._status_id}')
            lines.append(f'Status → {name}')
        if self._type_id is not None:
            name = (types or {}).get(self._type_id, f'#{self._type_id}')
            lines.append(f'Type → {name}')
        if self._priority_id is not None:
            name = (priorities or {}).get(self._priority_id, f'#{self._priority_id}')
            lines.append(f'Priority → {name}')
        if self._assignee_id is not None:
            name = (users or {}).get(self._assignee_id, f'#{self._assignee_id}')
            lines.append(f'Assignee → {name}')
        elif self._unassign:
            lines.append('Assignee → (none)')
        if self._subject is not None:
            lines.append(f'Subject → {self._subject!r}')
        if self._start_date is not None:
            lines.append(f'Start → {self._start_date}')
        if self._due_date is not None:
            lines.append(f'Due → {self._due_date}')
        return ', '.join(lines)
