from __future__ import annotations

from dataclasses import dataclass, field

from op.config import DefaultsConfig

_ID_FILTER_KEYS = ('type', 'status', 'priority', 'project', 'assignee', 'author')


@dataclass
class SearchQuery:
    task_id: int | None = None
    words: list[str] = field(default_factory=list)
    filters: dict[str, list[str]] = field(default_factory=dict)


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
    return SearchQuery(task_id=None, words=non_filter_tokens, filters=filters)


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


__all__ = ['SearchQuery', 'parse', '_ID_FILTER_KEYS']
