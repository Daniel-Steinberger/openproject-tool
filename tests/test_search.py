from __future__ import annotations

import pytest

from op.config import DefaultsConfig, RemoteConfig
from op.search import SearchQuery, build_api_filters, parse


class TestIdLookup:
    def test_single_number_is_id(self) -> None:
        q = parse(['1234'])
        assert q == SearchQuery(task_id=1234)

    def test_large_number(self) -> None:
        q = parse(['999999'])
        assert q.task_id == 999999

    def test_number_with_other_tokens_becomes_word(self) -> None:
        # `op 1234 foo` → user probably means title search, since they added a word.
        q = parse(['1234', 'foo'])
        assert q.task_id is None
        assert q.words == ['1234', 'foo']

    def test_number_plus_filter_still_id_lookup(self) -> None:
        # Filters don't change the id-lookup semantics when only a number is given.
        q = parse(['1234', 'type=bug'])
        assert q.task_id == 1234
        # Filters are ignored for id lookup (caller decides to honour them or not).


class TestWordSearch:
    def test_multiple_words(self) -> None:
        q = parse(['deployment', 'pipeline', 'bug'])
        assert q.task_id is None
        assert q.words == ['deployment', 'pipeline', 'bug']
        assert q.filters == {}


class TestFilters:
    def test_single_filter(self) -> None:
        q = parse(['type=bug'])
        assert q.filters == {'type': ['bug']}

    def test_multi_value_filter(self) -> None:
        q = parse(['type=bug,feature'])
        assert q.filters == {'type': ['bug', 'feature']}

    def test_multi_value_trims_whitespace(self) -> None:
        q = parse(['type=bug, feature , task'])
        assert q.filters == {'type': ['bug', 'feature', 'task']}

    def test_wildcard_filter_absent_from_filters(self) -> None:
        q = parse(['status=*'])
        assert q.filters == {}

    def test_combined(self) -> None:
        q = parse(['deploy', 'type=bug', 'status=*'])
        assert q.words == ['deploy']
        assert q.filters == {'type': ['bug']}

    def test_case_preserved_in_values(self) -> None:
        q = parse(['status=In Bearbeitung'])
        assert q.filters == {'status': ['In Bearbeitung']}

    def test_keys_are_lowercased(self) -> None:
        q = parse(['TYPE=bug'])
        assert q.filters == {'type': ['bug']}


class TestDefaults:
    def test_defaults_applied_when_no_filters_given(self) -> None:
        defaults = DefaultsConfig(status=['open'], type=['Task', 'Bug'])
        q = parse([], defaults=defaults)
        assert q.filters == {'status': ['open'], 'type': ['Task', 'Bug']}

    def test_explicit_filter_overrides_default(self) -> None:
        defaults = DefaultsConfig(status=['open'], type=['Task', 'Bug'])
        q = parse(['type=bug'], defaults=defaults)
        assert q.filters == {'status': ['open'], 'type': ['bug']}

    def test_wildcard_drops_default(self) -> None:
        defaults = DefaultsConfig(status=['open'], type=['Task', 'Bug'])
        q = parse(['status=*'], defaults=defaults)
        assert q.filters == {'type': ['Task', 'Bug']}
        assert 'status' not in q.filters

    def test_words_with_defaults(self) -> None:
        defaults = DefaultsConfig(status=['open'])
        q = parse(['deploy', 'bug'], defaults=defaults)
        assert q.words == ['deploy', 'bug']
        assert q.filters == {'status': ['open']}

    def test_defaults_ignored_for_id_lookup(self) -> None:
        defaults = DefaultsConfig(status=['open'])
        q = parse(['1234'], defaults=defaults)
        assert q.task_id == 1234
        assert q.filters == {}
        assert q.words == []

    def test_tracks_default_keys(self) -> None:
        defaults = DefaultsConfig(status=['open'], type=['Task'])
        q = parse(['type=bug'], defaults=defaults)
        # 'type' was explicit, 'status' came from defaults
        assert q.default_filter_keys == {'status'}

    def test_all_filters_explicit_no_default_keys(self) -> None:
        defaults = DefaultsConfig(status=['open'], type=['Task'])
        q = parse(['type=bug', 'status=*'], defaults=defaults)
        assert q.default_filter_keys == set()


class TestEdgeCases:
    def test_empty_input(self) -> None:
        q = parse([])
        assert q == SearchQuery()

    def test_empty_input_with_defaults(self) -> None:
        defaults = DefaultsConfig(status=['open'])
        q = parse([], defaults=defaults)
        assert q.filters == {'status': ['open']}

    def test_empty_value_treated_as_wildcard(self) -> None:
        # `status=` (empty) — treat as wildcard to be forgiving.
        q = parse(['status='])
        assert q.filters == {}

    def test_value_with_equals_sign(self) -> None:
        # `key=a=b` — everything after first = is the value.
        q = parse(['custom=a=b'])
        assert q.filters == {'custom': ['a=b']}


class TestBuildApiFilters:
    def test_empty_query(self) -> None:
        assert build_api_filters(SearchQuery(), RemoteConfig()) == []

    def test_type_name_resolved_to_id(self) -> None:
        remote = RemoteConfig(types={1: 'Task', 2: 'Bug'})
        q = SearchQuery(filters={'type': ['Bug']})
        assert build_api_filters(q, remote) == [
            {'type_id': {'operator': '=', 'values': ['2']}}
        ]

    def test_type_case_insensitive(self) -> None:
        remote = RemoteConfig(types={1: 'Task', 2: 'Bug'})
        q = SearchQuery(filters={'type': ['bug']})
        assert build_api_filters(q, remote) == [
            {'type_id': {'operator': '=', 'values': ['2']}}
        ]

    def test_multi_value_filter(self) -> None:
        remote = RemoteConfig(types={1: 'Task', 2: 'Bug', 3: 'Feature'})
        q = SearchQuery(filters={'type': ['task', 'feature']})
        assert build_api_filters(q, remote) == [
            {'type_id': {'operator': '=', 'values': ['1', '3']}}
        ]

    def test_status_open_meta(self) -> None:
        q = SearchQuery(filters={'status': ['open']})
        assert build_api_filters(q, RemoteConfig()) == [{'status': {'operator': 'o'}}]

    def test_status_closed_meta(self) -> None:
        q = SearchQuery(filters={'status': ['closed']})
        assert build_api_filters(q, RemoteConfig()) == [{'status': {'operator': 'c'}}]

    def test_status_named(self) -> None:
        remote = RemoteConfig(statuses={1: 'Neu', 2: 'In Bearbeitung'})
        q = SearchQuery(filters={'status': ['in bearbeitung']})
        assert build_api_filters(q, remote) == [
            {'status_id': {'operator': '=', 'values': ['2']}}
        ]

    def test_priority_named(self) -> None:
        remote = RemoteConfig(priorities={8: 'Normal', 9: 'Hoch'})
        q = SearchQuery(filters={'priority': ['hoch']})
        assert build_api_filters(q, remote) == [
            {'priority_id': {'operator': '=', 'values': ['9']}}
        ]

    def test_project_named(self) -> None:
        remote = RemoteConfig(projects={10: 'Web', 11: 'Mobile'})
        q = SearchQuery(filters={'project': ['mobile']})
        assert build_api_filters(q, remote) == [
            {'project_id': {'operator': '=', 'values': ['11']}}
        ]

    def test_assignee_named(self) -> None:
        remote = RemoteConfig(users={5: 'Max Mustermann'})
        q = SearchQuery(filters={'assignee': ['Max Mustermann']})
        assert build_api_filters(q, remote) == [
            {'assignee_id': {'operator': '=', 'values': ['5']}}
        ]

    def test_unknown_value_raises(self) -> None:
        remote = RemoteConfig(types={1: 'Task'})
        q = SearchQuery(filters={'type': ['wut']})
        with pytest.raises(ValueError, match='type'):
            build_api_filters(q, remote)

    def test_unknown_value_message_lists_valid_values(self) -> None:
        remote = RemoteConfig(types={1: 'Task', 2: 'Bug'})
        q = SearchQuery(filters={'type': ['Feature']})
        with pytest.raises(ValueError) as excinfo:
            build_api_filters(q, remote)
        message = str(excinfo.value)
        assert 'Feature' in message
        assert 'Task' in message
        assert 'Bug' in message

    def test_default_filter_drops_unresolved_values(self) -> None:
        """Default values that don't resolve must not crash — only the missing values are dropped."""
        remote = RemoteConfig(types={1: 'Task', 2: 'Bug'})
        q = SearchQuery(
            filters={'type': ['Task', 'Feature', 'Bug']},
            default_filter_keys={'type'},
        )
        assert build_api_filters(q, remote) == [
            {'type_id': {'operator': '=', 'values': ['1', '2']}}
        ]

    def test_default_filter_with_all_unresolved_is_dropped(self) -> None:
        remote = RemoteConfig(types={1: 'Task'})
        q = SearchQuery(
            filters={'type': ['Feature', 'Epic']},
            default_filter_keys={'type'},
        )
        assert build_api_filters(q, remote) == []

    def test_explicit_filter_still_raises_on_unknown(self) -> None:
        """An explicit user input (not from defaults) must still error hard."""
        remote = RemoteConfig(types={1: 'Task'})
        q = SearchQuery(filters={'type': ['Feature']}, default_filter_keys=set())
        with pytest.raises(ValueError):
            build_api_filters(q, remote)

    def test_words_add_subject_contains_filters(self) -> None:
        q = SearchQuery(words=['deploy', 'bug'])
        assert build_api_filters(q, RemoteConfig()) == [
            {'subject': {'operator': '~', 'values': ['deploy']}},
            {'subject': {'operator': '~', 'values': ['bug']}},
        ]

    def test_combined(self) -> None:
        remote = RemoteConfig(types={1: 'Task', 2: 'Bug'})
        q = SearchQuery(
            words=['deploy'], filters={'status': ['open'], 'type': ['bug']}
        )
        assert build_api_filters(q, remote) == [
            {'subject': {'operator': '~', 'values': ['deploy']}},
            {'status': {'operator': 'o'}},
            {'type_id': {'operator': '=', 'values': ['2']}},
        ]

    def test_unknown_key_raises(self) -> None:
        q = SearchQuery(filters={'bogus': ['x']})
        with pytest.raises(ValueError, match='bogus'):
            build_api_filters(q, RemoteConfig())
