from __future__ import annotations

import os
import typing as T
from pathlib import Path

import tomlkit
from pydantic import BaseModel, Field

_DEFAULT_CONFIG_TEMPLATE = """\
[connection]
# OpenProject base URL (without trailing slash)
base_url = "https://your-openproject.example.com"

# API key authentication — choose one method:
#
#   Method 1 (recommended): set the environment variable OP_API_KEY.
#     The variable always takes precedence over the api_key entry below.
#
#   Method 2: uncomment the api_key line below and set your key.
#     WARNING: the key is stored in plain text. Ensure the file is only
#     readable by your user: chmod 600 on this file.
#
# api_key = "your-api-key-here"


[defaults]
# Default filters applied when not specified on the command line.
# Use `key=*` on the command line to override a default for a single query.
status = ["open"]
type = ["Task", "Bug", "Feature"]


[logging]
# Diagnostic log — useful for debugging API errors, TUI issues and update failures.
# Level: DEBUG, INFO (default), WARNING, ERROR
# File defaults to $XDG_STATE_HOME/openproject-tool/op.log (or ~/.local/state/…)
# level = "INFO"
# file = "/path/to/op.log"


[filter]
# Project filter — hide tasks that belong to projects you aren't interested in.
# Both values are auto-maintained by the TUI (hotkey `p` toggles, project
# selector dialog edits the list).
# irrelevant_projects = [10, 11]
# project_filter_active = false


[remote]
# This section is auto-populated by: op --load-remote-data
# Do not edit manually — your changes will be overwritten.

[remote.statuses]

[remote.types]

[remote.priorities]

[remote.users]

[remote.groups]

[remote.projects]

[remote.custom_fields]
"""


class ConnectionConfig(BaseModel):
    base_url: str
    api_key: str | None = None


class DefaultsConfig(BaseModel):
    status: list[str] = Field(default_factory=list)
    type: list[str] = Field(default_factory=list)


class RemoteConfig(BaseModel):
    statuses: dict[int, str] = Field(default_factory=dict)
    types: dict[int, str] = Field(default_factory=dict)
    priorities: dict[int, str] = Field(default_factory=dict)
    users: dict[int, str] = Field(default_factory=dict)
    groups: dict[int, str] = Field(default_factory=dict)
    projects: dict[int, str] = Field(default_factory=dict)
    project_parents: dict[int, int] = Field(default_factory=dict)
    custom_fields: dict[int, str] = Field(default_factory=dict)
    custom_field_users: dict[int, dict[int, str]] = Field(default_factory=dict)
    custom_field_options: dict[int, dict[int, str]] = Field(default_factory=dict)

    @property
    def pm_users(self) -> dict[int, str]:
        """Allowed values for the PM custom field (customField42).

        CF#42 can be user-type (returns custom_field_users) or list-type/CustomOption
        (returns custom_field_options). Falls back between the two so callers don't
        need to know the underlying field format.
        """
        return self.custom_field_users.get(42, {}) or self.custom_field_options.get(42, {})


class FilterConfig(BaseModel):
    irrelevant_projects: list[int] = Field(default_factory=list)
    project_filter_active: bool = False


class LoggingConfig(BaseModel):
    level: str = 'INFO'
    file: Path | None = None


class Config(BaseModel):
    connection: ConnectionConfig
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    remote: RemoteConfig = Field(default_factory=RemoteConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    filter: FilterConfig = Field(default_factory=FilterConfig)


def default_config_path() -> Path:
    """Return the XDG-compliant default config file path."""
    xdg = os.environ.get('XDG_CONFIG_HOME')
    base = Path(xdg) if xdg else Path.home() / '.config'
    return base / 'openproject-tool' / 'config.toml'


def load_config(path: Path | None = None) -> Config:
    """Read config from `path`; create a default template if the file does not exist."""
    if path is None:
        path = default_config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_CONFIG_TEMPLATE)
    data = tomlkit.parse(path.read_text()).unwrap()
    return Config.model_validate(_normalise(data))


def get_api_key(config: Config) -> str | None:
    """Return API key — env var OP_API_KEY takes precedence, falls back to config file."""
    env = os.environ.get('OP_API_KEY')
    if env:
        return env
    return config.connection.api_key


def update_remote(
    path: Path,
    *,
    statuses: dict[int, str] | None = None,
    types: dict[int, str] | None = None,
    priorities: dict[int, str] | None = None,
    users: dict[int, str] | None = None,
    groups: dict[int, str] | None = None,
    projects: dict[int, str] | None = None,
    project_parents: dict[int, int] | None = None,
    custom_fields: dict[int, str] | None = None,
    custom_field_users: dict[int, dict[int, str]] | None = None,
    custom_field_options: dict[int, dict[int, str]] | None = None,
) -> None:
    """Replace the given remote subtables in-place, preserving comments and unrelated sections."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_CONFIG_TEMPLATE)

    doc = tomlkit.parse(path.read_text())
    remote = doc.setdefault('remote', tomlkit.table())

    flat_updates = {
        'statuses': statuses,
        'types': types,
        'priorities': priorities,
        'users': users,
        'groups': groups,
        'projects': projects,
        'project_parents': project_parents,
        'custom_fields': custom_fields,
    }
    for name, values in flat_updates.items():
        if values is None:
            continue
        table = tomlkit.table()
        for key, value in values.items():
            table[str(key)] = value
        remote[name] = table

    if custom_field_users is not None:
        outer = tomlkit.table()
        for cf_id, uid_map in custom_field_users.items():
            inner = tomlkit.table()
            for uid, name in uid_map.items():
                inner[str(uid)] = name
            outer[str(cf_id)] = inner
        remote['custom_field_users'] = outer

    if custom_field_options is not None:
        outer = tomlkit.table()
        for cf_id, opt_map in custom_field_options.items():
            inner = tomlkit.table()
            for opt_id, value in opt_map.items():
                inner[str(opt_id)] = value
            outer[str(cf_id)] = inner
        remote['custom_field_options'] = outer

    path.write_text(tomlkit.dumps(doc))


def update_filter(
    path: Path,
    *,
    irrelevant_projects: list[int] | None = None,
    project_filter_active: bool | None = None,
) -> None:
    """Persist the project-filter state to the `[filter]` section."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_CONFIG_TEMPLATE)

    doc = tomlkit.parse(path.read_text())
    filter_table = doc.setdefault('filter', tomlkit.table())

    if irrelevant_projects is not None:
        arr = tomlkit.array()
        for pid in irrelevant_projects:
            arr.append(pid)
        filter_table['irrelevant_projects'] = arr
    if project_filter_active is not None:
        filter_table['project_filter_active'] = project_filter_active

    path.write_text(tomlkit.dumps(doc))


def _normalise(data: dict[str, T.Any]) -> dict[str, T.Any]:
    """Ensure all expected top-level sections exist for Pydantic validation."""
    data.setdefault('connection', {})
    data.setdefault('defaults', {})
    data.setdefault('remote', {})
    data.setdefault('logging', {})
    data.setdefault('filter', {})
    return data
