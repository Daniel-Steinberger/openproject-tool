from __future__ import annotations

import logging
import typing as T
from dataclasses import dataclass, field

from op.config import DefaultsConfig, RemoteConfig

log = logging.getLogger(__name__)

_FILTER_KEY_MAP: dict[str, tuple[str, tuple[str, ...]]] = {
    # user-facing key: (OpenProject filter key, lookup sources on RemoteConfig)
    # Note: OpenProject uses "assigned_to_id" and "author_id" — not "assignee_id".
    'type': ('type_id', ('types',)),
    'status': ('status_id', ('statuses',)),
    'priority': ('priority_id', ('priorities',)),
    'project': ('project_id', ('projects',)),
    'assignee': ('assigned_to_id', ('users', 'groups')),
    'author': ('author_id', ('users',)),
}


@dataclass
class SearchQuery:
    task_id: int | None = None
    words: list[str] = field(default_factory=list)
    filters: dict[str, list[str]] = field(default_factory=dict)
    default_filter_keys: set[str] = field(default_factory=set)


def parse(tokens: list[str], *, defaults: DefaultsConfig | None = None) -> SearchQuery:
    """Parse CLI tokens into a SearchQuery, applying default filters where no override is given."""
    explicit_filters: dict[str, list[str]] = {}
    wildcard_keys: set[str] = set()
    non_filter_tokens: list[str] = []

    for token in tokens:
        if '=' in token:
            key, raw_value = token.split('=', 1)
            key = key.strip().lower()
            value = raw_value.strip()
            if value in ('', '*'):
                wildcard_keys.add(key)
            else:
                explicit_filters[key] = [v.strip() for v in value.split(',') if v.strip()]
        else:
            non_filter_tokens.append(token)

    if len(tokens) == 1 and non_filter_tokens == tokens and tokens[0].isdigit():
        return SearchQuery(task_id=int(tokens[0]))
    if len(non_filter_tokens) == 1 and non_filter_tokens[0].isdigit() and (
        explicit_filters or wildcard_keys
    ):
        return SearchQuery(task_id=int(non_filter_tokens[0]))

    filters = _merge_with_defaults(explicit_filters, wildcard_keys, defaults)
    default_filter_keys = set(filters) - set(explicit_filters)
    return SearchQuery(
        task_id=None,
        words=non_filter_tokens,
        filters=filters,
        default_filter_keys=default_filter_keys,
    )


def _merge_with_defaults(
    explicit: dict[str, list[str]],
    wildcard_keys: set[str],
    defaults: DefaultsConfig | None,
) -> dict[str, list[str]]:
    merged = dict(explicit)
    if defaults is None:
        return merged
    for key, values in _defaults_as_dict(defaults).items():
        if key in merged or key in wildcard_keys:
            continue
        merged[key] = list(values)
    return merged


def _defaults_as_dict(defaults: DefaultsConfig) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if defaults.status:
        result['status'] = defaults.status
    if defaults.type:
        result['type'] = defaults.type
    return result


def build_api_filters(
    query: SearchQuery, remote: RemoteConfig
) -> list[dict[str, T.Any]]:
    """Translate a SearchQuery into the OpenProject filter-JSON array.

    Values from user-supplied filters that cannot be resolved raise `ValueError`.
    Values from default filters are dropped with a warning — a stale default should
    not block the entire search.
    """
    api_filters: list[dict[str, T.Any]] = []

    for word in query.words:
        api_filters.append({'subject': {'operator': '~', 'values': [word]}})

    for key, values in query.filters.items():
        if key == 'status' and _is_meta_status(values):
            api_filters.append({'status': {'operator': values[0].lower()[0]}})
            continue
        if key not in _FILTER_KEY_MAP:
            valid = ', '.join(sorted(_FILTER_KEY_MAP))
            raise ValueError(f'Unknown filter key: {key!r}. Valid keys: {valid}')
        op_key, remote_attrs = _FILTER_KEY_MAP[key]
        merged_lookup: dict[int, str] = {}
        for attr in remote_attrs:
            merged_lookup.update(getattr(remote, attr))
        is_default = key in query.default_filter_keys

        resolved_ids: list[str] = []
        for value in values:
            try:
                entity_id, resolved_name = _resolve_value(value, merged_lookup)
            except _AmbiguousMatch as amb:
                raise ValueError(
                    f'Ambiguous {key} value: {value!r}. '
                    f'Matches: {", ".join(amb.candidates)}'
                ) from None
            if entity_id is None:
                if is_default:
                    log.warning(
                        'Dropping default %s value %r — not known on remote',
                        key,
                        value,
                    )
                    continue
                valid_values = (
                    ', '.join(sorted(merged_lookup.values())) or '(none loaded)'
                )
                raise ValueError(
                    f'Unknown {key} value: {value!r}. Valid values: {valid_values}'
                )
            if resolved_name != value:
                log.info(
                    'Resolved %s %r → %r (id=%d)',
                    key,
                    value,
                    resolved_name,
                    entity_id,
                )
            resolved_ids.append(str(entity_id))

        if resolved_ids:
            api_filters.append({op_key: {'operator': '=', 'values': resolved_ids}})

    return api_filters


def _is_meta_status(values: list[str]) -> bool:
    return len(values) == 1 and values[0].lower() in ('open', 'closed')


def _lookup_name(value: str, lookup: dict[int, str]) -> int | None:
    needle = value.casefold()
    for entity_id, name in lookup.items():
        if name.casefold() == needle:
            return entity_id
    return None


class _AmbiguousMatch(Exception):
    """Raised when a fuzzy value matches more than one entry in the lookup."""

    def __init__(self, candidates: list[str]) -> None:
        super().__init__(f'ambiguous: {candidates}')
        self.candidates = candidates


def _resolve_value(
    value: str, lookup: dict[int, str]
) -> tuple[int | None, str]:
    """Resolve a user-supplied filter value.

    - Exact (case-fold) match wins, returns (id, value).
    - Otherwise, case-fold substring match:
        * exactly 1 hit → return (id, resolved_name)
        * multiple hits → raise _AmbiguousMatch with the candidate names
        * no hits → return (None, value)
    """
    exact = _lookup_name(value, lookup)
    if exact is not None:
        return exact, value

    needle = value.casefold()
    matches = [
        (entity_id, name)
        for entity_id, name in lookup.items()
        if needle in name.casefold()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise _AmbiguousMatch(sorted(name for _, name in matches))
    return None, value


_FIELDS_FOR_EDITOR = ('status', 'type', 'priority', 'project', 'assignee', 'author')


def query_to_field_strings(query: SearchQuery) -> dict[str, str]:
    """Serialise a SearchQuery to the flat string form used by the FilterScreen inputs.

    Inverse: the user edits the strings, we join them to tokens, and hand them
    back to `parse()` — which is the same path the CLI uses.
    """
    result: dict[str, str] = {'words': ' '.join(query.words)}
    for field in _FIELDS_FOR_EDITOR:
        values = query.filters.get(field, [])
        result[field] = ', '.join(values)
    return result


__all__ = [
    'SearchQuery',
    'parse',
    'build_api_filters',
    'query_to_field_strings',
]
