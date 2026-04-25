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
        self._project_id: int | None = None
        self._assignee_id: int | None = None
        self._assignee_is_group: bool = False
        self._unassign: bool = False
        self._subject: str | None = None
        self._description: str | None = None
        self._start_date: str | None = None
        self._due_date: str | None = None
        self._add_watcher_ids: list[int] = []
        self._remove_watcher_ids: list[int] = []
        self._custom_field_links: dict[int, int | None] = {}
        self._custom_field_options: dict[int, int | None] = {}

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
    def project_id(self) -> int | None:
        return self._project_id

    @project_id.setter
    def project_id(self, value: int | None) -> None:
        self._project_id = value

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

    # --- watcher changes -------------------------------------------------

    def add_watcher(self, user_id: int) -> None:
        if user_id not in self._add_watcher_ids:
            self._add_watcher_ids.append(user_id)

    def remove_watcher(self, user_id: int) -> None:
        if user_id not in self._remove_watcher_ids:
            self._remove_watcher_ids.append(user_id)

    @property
    def add_watcher_ids(self) -> list[int]:
        return list(self._add_watcher_ids)

    @property
    def remove_watcher_ids(self) -> list[int]:
        return list(self._remove_watcher_ids)

    @property
    def has_watcher_changes(self) -> bool:
        return bool(self._add_watcher_ids) or bool(self._remove_watcher_ids)

    # --- custom field link fields ----------------------------------------

    def set_custom_field_user(self, cf_id: int, user_id: int | None) -> None:
        """Set (or clear) a user-type custom field. Pass None to explicitly clear."""
        self._custom_field_links[cf_id] = user_id

    def set_custom_field_option(self, cf_id: int, option_id: int | None) -> None:
        """Set (or clear) a list-type custom field. Pass None to explicitly clear."""
        self._custom_field_options[cf_id] = option_id

    # --- derived ---------------------------------------------------------

    @property
    def has_patch_changes(self) -> bool:
        return bool(self.api_changes())

    @property
    def has_changes(self) -> bool:
        return self.has_patch_changes or self.has_watcher_changes

    def merge_from(self, other: UpdateForm) -> None:
        """Fold `other` into this form — last-writer-wins per field.

        Used when a task in the pending-queue gets re-edited: the second edit
        doesn't replace the whole form, it overlays only the fields the user
        touched this time.
        """
        if other._status_id is not None:
            self._status_id = other._status_id
        if other._type_id is not None:
            self._type_id = other._type_id
        if other._priority_id is not None:
            self._priority_id = other._priority_id
        if other._project_id is not None:
            self._project_id = other._project_id

        # assignee: either side may switch between user-id and unassign-flag
        if other._assignee_id is not None:
            self._assignee_id = other._assignee_id
            self._assignee_is_group = other._assignee_is_group
            self._unassign = False
        elif other._unassign:
            self._unassign = True
            self._assignee_id = None

        if other._subject is not None:
            self._subject = other._subject
        if other._description is not None:
            self._description = other._description
        if other._start_date is not None:
            self._start_date = other._start_date
        if other._due_date is not None:
            self._due_date = other._due_date

        # watcher lists: accumulate via set-union (deduplicated)
        merged_add = set(self._add_watcher_ids)
        merged_add.update(other._add_watcher_ids)
        self._add_watcher_ids = list(merged_add)

        merged_remove = set(self._remove_watcher_ids)
        merged_remove.update(other._remove_watcher_ids)
        self._remove_watcher_ids = list(merged_remove)

        # custom field links: last-writer-wins per field
        for cf_id, user_id in other._custom_field_links.items():
            self._custom_field_links[cf_id] = user_id
        for cf_id, option_id in other._custom_field_options.items():
            self._custom_field_options[cf_id] = option_id

    def api_changes(self) -> dict[str, T.Any]:
        changes: dict[str, T.Any] = {}

        links: dict[str, dict[str, T.Any]] = {}
        if self._status_id is not None:
            links['status'] = {'href': f'/api/v3/statuses/{self._status_id}'}
        if self._type_id is not None:
            links['type'] = {'href': f'/api/v3/types/{self._type_id}'}
        if self._priority_id is not None:
            links['priority'] = {'href': f'/api/v3/priorities/{self._priority_id}'}
        if self._project_id is not None:
            links['project'] = {'href': f'/api/v3/projects/{self._project_id}'}
        if self._assignee_id is not None:
            kind = 'groups' if self._assignee_is_group else 'users'
            links['assignee'] = {'href': f'/api/v3/{kind}/{self._assignee_id}'}
        elif self._unassign:
            links['assignee'] = {'href': None}
        for cf_id, user_id in self._custom_field_links.items():
            if user_id is not None:
                links[f'customField{cf_id}'] = {'href': f'/api/v3/users/{user_id}'}
            else:
                links[f'customField{cf_id}'] = {'href': None}
        for cf_id, option_id in self._custom_field_options.items():
            if option_id is not None:
                links[f'customField{cf_id}'] = {'href': f'/api/v3/custom_options/{option_id}'}
            else:
                links[f'customField{cf_id}'] = {'href': None}
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
        projects: dict[int, str] | None = None,
        users: dict[int, str] | None = None,
        custom_fields: dict[int, str] | None = None,
        custom_field_options: dict[int, dict[int, str]] | None = None,
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
        if self._project_id is not None:
            name = (projects or {}).get(self._project_id, f'#{self._project_id}')
            lines.append(f'Project → {name}')
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
        watcher_parts: list[str] = []
        for uid in self._add_watcher_ids:
            watcher_parts.append(f'+{(users or {}).get(uid, f"#{uid}")}')
        for uid in self._remove_watcher_ids:
            watcher_parts.append(f'-{(users or {}).get(uid, f"#{uid}")}')
        if watcher_parts:
            lines.append(f'Watchers {" ".join(watcher_parts)}')
        for cf_id, user_id in self._custom_field_links.items():
            cf_name = (custom_fields or {}).get(cf_id, f'CF#{cf_id}')
            user_name = (users or {}).get(user_id, f'#{user_id}') if user_id is not None else '(none)'
            lines.append(f'{cf_name} → {user_name}')
        for cf_id, option_id in self._custom_field_options.items():
            cf_name = (custom_fields or {}).get(cf_id, f'CF#{cf_id}')
            cf_opts = (custom_field_options or {}).get(cf_id, {})
            opt_name = cf_opts.get(option_id, f'#{option_id}') if option_id is not None else '(none)'
            lines.append(f'{cf_name} → {opt_name}')
        return ', '.join(lines)
