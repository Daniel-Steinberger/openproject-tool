from __future__ import annotations

import os
import typing as T
from pathlib import Path
from typing import Annotated

import tomlkit
from pydantic import BaseModel, BeforeValidator, Field

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

# Ignore list — individual tasks to hide from the task list.
# Managed via the `i` hotkey (toggle) and the command palette → "Ignored tasks".
# ignored_tasks = [42, 99]
# ignore_filter_active = true


[keybindings]
# Keyboard shortcuts. Use ^ as Ctrl shorthand (e.g. ^g = ctrl+g).
# Uncomment any subsection below to override the defaults for that screen.

# [keybindings.main]
# toggle        = "space"   # mark/unmark task
# invert        = "v"       # invert selection
# ignore        = "i"       # ignore/unignore current task
# edit          = "u"       # open edit dialog
# apply         = "g"       # go to review/apply queue
# filter        = "f"       # open filter dialog
# open          = "o"       # open in browser
# project_filter = "p"      # toggle project filter
# quit          = "q"

# [keybindings.detail]
# close         = "q"
# edit          = "e"
# comment       = "c"
# open          = "o"       # open in browser
# search        = "slash"   # '/' — search forward
# search_next   = "n"       # next search match

# [keybindings.update_modal]
# apply         = "g"
# cancel        = "q"
# pick_date     = "ctrl+d"  # open calendar picker
# today         = "ctrl+t"  # insert today's date
# next_free     = "ctrl+n"  # insert next non-busy day

# [keybindings.filter]
# apply         = "ctrl+g"

# [keybindings.project_filter]
# toggle        = "space"
# invert        = "i"
# save          = "q"

# [keybindings.review]
# edit          = "e"
# delete        = "d"
# apply         = "g"
# back          = "q"

# [keybindings.comment]
# submit        = "ctrl+s"

# [keybindings.calendar]
# prev_month    = "pageup"
# next_month    = "pagedown"
# today         = "ctrl+t"
# next_free     = "ctrl+n"

# [keybindings.applying]
# close         = "q"

# [keybindings.ignore_list]
# unignore      = "space"   # remove task from ignore list
# filter_toggle = "f"       # toggle ignore filter on/off
# save          = "q"


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


def normalize_key(key: str) -> str:
    """Normalize ^x shorthand to ctrl+x (e.g. ^g → ctrl+g)."""
    if len(key) >= 2 and key[0] == '^':
        return f'ctrl+{key[1:]}'
    return key


KeyStr = Annotated[str, BeforeValidator(normalize_key)]


class MainKeybindings(BaseModel):
    toggle: KeyStr = 'space'
    invert: KeyStr = 'v'
    ignore: KeyStr = 'i'
    edit: KeyStr = 'u'
    apply: KeyStr = 'g'
    filter: KeyStr = 'f'
    open: KeyStr = 'o'
    project_filter: KeyStr = 'p'
    quit: KeyStr = 'q'


class DetailKeybindings(BaseModel):
    close: KeyStr = 'q'
    edit: KeyStr = 'e'
    comment: KeyStr = 'c'
    open: KeyStr = 'o'
    search: KeyStr = 'slash'
    search_next: KeyStr = 'n'


class UpdateModalKeybindings(BaseModel):
    apply: KeyStr = 'g'
    cancel: KeyStr = 'q'
    pick_date: KeyStr = 'ctrl+d'
    today: KeyStr = 'ctrl+t'
    next_free: KeyStr = 'ctrl+n'


class FilterKeybindings(BaseModel):
    apply: KeyStr = 'ctrl+g'


class ProjectFilterKeybindings(BaseModel):
    toggle: KeyStr = 'space'
    invert: KeyStr = 'i'
    save: KeyStr = 'q'


class ReviewKeybindings(BaseModel):
    edit: KeyStr = 'e'
    delete: KeyStr = 'd'
    apply: KeyStr = 'g'
    back: KeyStr = 'q'


class CommentKeybindings(BaseModel):
    submit: KeyStr = 'ctrl+s'


class CalendarKeybindings(BaseModel):
    prev_month: KeyStr = 'pageup'
    next_month: KeyStr = 'pagedown'
    today: KeyStr = 'ctrl+t'
    next_free: KeyStr = 'ctrl+n'


class IgnoreListKeybindings(BaseModel):
    unignore: KeyStr = 'space'
    filter_toggle: KeyStr = 'f'
    save: KeyStr = 'q'


class ApplyingKeybindings(BaseModel):
    close: KeyStr = 'q'


class KeybindingsConfig(BaseModel):
    main: MainKeybindings = Field(default_factory=MainKeybindings)
    detail: DetailKeybindings = Field(default_factory=DetailKeybindings)
    update_modal: UpdateModalKeybindings = Field(default_factory=UpdateModalKeybindings)
    filter: FilterKeybindings = Field(default_factory=FilterKeybindings)
    project_filter: ProjectFilterKeybindings = Field(default_factory=ProjectFilterKeybindings)
    review: ReviewKeybindings = Field(default_factory=ReviewKeybindings)
    comment: CommentKeybindings = Field(default_factory=CommentKeybindings)
    calendar: CalendarKeybindings = Field(default_factory=CalendarKeybindings)
    applying: ApplyingKeybindings = Field(default_factory=ApplyingKeybindings)
    ignore_list: IgnoreListKeybindings = Field(default_factory=IgnoreListKeybindings)


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
    ignored_tasks: list[int] = Field(default_factory=list)
    ignore_filter_active: bool = True


class LoggingConfig(BaseModel):
    level: str = 'INFO'
    file: Path | None = None


class Config(BaseModel):
    connection: ConnectionConfig
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    remote: RemoteConfig = Field(default_factory=RemoteConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    filter: FilterConfig = Field(default_factory=FilterConfig)
    keybindings: KeybindingsConfig = Field(default_factory=KeybindingsConfig)


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
    doc = tomlkit.parse(path.read_text())
    _migrate_keybindings(path, doc)
    data = doc.unwrap()
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
    ignored_tasks: list[int] | None = None,
    ignore_filter_active: bool | None = None,
) -> None:
    """Persist the filter state to the `[filter]` section."""
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
    if ignored_tasks is not None:
        arr = tomlkit.array()
        for tid in ignored_tasks:
            arr.append(tid)
        filter_table['ignored_tasks'] = arr
    if ignore_filter_active is not None:
        filter_table['ignore_filter_active'] = ignore_filter_active

    path.write_text(tomlkit.dumps(doc))


# Inline comments for every keybinding — shown in the config file next to each key.
_KB_COMMENTS: dict[str, dict[str, str]] = {
    'main': {
        'toggle': 'mark/unmark task',
        'invert': 'invert selection',
        'ignore': 'ignore/unignore current task',
        'edit': 'open edit dialog',
        'apply': 'go to review/apply queue',
        'filter': 'open filter dialog',
        'open': 'open in browser',
        'project_filter': 'toggle project filter',
        'quit': '',
    },
    'detail': {
        'close': '',
        'edit': '',
        'comment': '',
        'open': 'open in browser',
        'search': "'/' — search forward",
        'search_next': 'next search match',
    },
    'update_modal': {
        'apply': '',
        'cancel': '',
        'pick_date': 'open calendar picker',
        'today': "insert today's date",
        'next_free': 'insert next non-busy day',
    },
    'filter': {
        'apply': '',
    },
    'project_filter': {
        'toggle': '',
        'invert': '',
        'save': '',
    },
    'review': {
        'edit': '',
        'delete': '',
        'apply': '',
        'back': '',
    },
    'comment': {
        'submit': '',
    },
    'calendar': {
        'prev_month': '',
        'next_month': '',
        'today': '',
        'next_free': '',
    },
    'applying': {
        'close': '',
    },
    'ignore_list': {
        'unignore': 'remove task from ignore list',
        'filter_toggle': 'toggle ignore filter on/off',
        'save': '',
    },
}


def _kb_item(value: str, comment: str) -> tomlkit.items.Item:
    item = tomlkit.item(value)
    if comment:
        item.comment(comment)
    return item


def _migrate_keybindings(path: Path, doc: tomlkit.TOMLDocument) -> None:
    """Ensure [keybindings] and all its subsections are present with all keys.

    Missing subsections are added with default values and inline comments.
    Missing keys within existing subsections are added with their defaults.
    Rewrites the file only when something changed.
    """
    changed = False
    if 'keybindings' not in doc:
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment(
            ' Keyboard shortcuts. Use ^ as Ctrl shorthand (e.g. ^g = ctrl+g).'
        ))
        doc.add(tomlkit.comment(
            ' All keys are listed with their defaults; change any value to customize.'
        ))
        doc['keybindings'] = tomlkit.table()
        changed = True

    kb_doc = doc['keybindings']
    defaults = KeybindingsConfig()
    for field_name in KeybindingsConfig.model_fields:
        sub_defaults = getattr(defaults, field_name).model_dump()
        comments = _KB_COMMENTS.get(field_name, {})
        if field_name not in kb_doc:
            sub = tomlkit.table()
            for key, val in sub_defaults.items():
                sub.add(key, _kb_item(val, comments.get(key, '')))
            kb_doc.add(field_name, sub)
            changed = True
        else:
            for key, val in sub_defaults.items():
                if key not in kb_doc[field_name]:
                    kb_doc[field_name].add(key, _kb_item(val, comments.get(key, '')))
                    changed = True
    if changed:
        path.write_text(tomlkit.dumps(doc))


def _normalise(data: dict[str, T.Any]) -> dict[str, T.Any]:
    """Ensure all expected top-level sections exist for Pydantic validation."""
    data.setdefault('connection', {})
    data.setdefault('defaults', {})
    data.setdefault('remote', {})
    data.setdefault('logging', {})
    data.setdefault('filter', {})
    data.setdefault('keybindings', {})
    return data
