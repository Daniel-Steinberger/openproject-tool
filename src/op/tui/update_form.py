from __future__ import annotations

import typing as T


class UpdateForm:
    """Pending-changes state for the batch-update modal.

    Each attribute is `None` (unchanged) or holds the desired new value.
    Call `api_changes()` to obtain the JSON-ready PATCH body for OpenProject.
    """

    def __init__(self) -> None:
        self._status_id: int | None = None
        self._type_id: int | None = None
        self._priority_id: int | None = None
        self._assignee_id: int | None = None
        self._unassign: bool = False

    # --- fields ----------------------------------------------------------

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
        if value is not None:
            self._unassign = False

    @property
    def unassign(self) -> bool:
        return self._unassign

    @unassign.setter
    def unassign(self, value: bool) -> None:
        self._unassign = value
        if value:
            self._assignee_id = None

    # --- derived ---------------------------------------------------------

    @property
    def has_changes(self) -> bool:
        return bool(self.api_changes())

    def api_changes(self) -> dict[str, T.Any]:
        links: dict[str, dict[str, T.Any]] = {}
        if self._status_id is not None:
            links['status'] = {'href': f'/api/v3/statuses/{self._status_id}'}
        if self._type_id is not None:
            links['type'] = {'href': f'/api/v3/types/{self._type_id}'}
        if self._priority_id is not None:
            links['priority'] = {'href': f'/api/v3/priorities/{self._priority_id}'}
        if self._assignee_id is not None:
            links['assignee'] = {'href': f'/api/v3/users/{self._assignee_id}'}
        elif self._unassign:
            links['assignee'] = {'href': None}
        return {'_links': links} if links else {}

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
        return ', '.join(lines)
