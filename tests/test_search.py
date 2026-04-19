from __future__ import annotations

from op.config import DefaultsConfig
from op.search import SearchQuery, parse


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
