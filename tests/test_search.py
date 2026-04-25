from __future__ import annotations

import pytest

from op.config import DefaultsConfig, RemoteConfig
from op.search import SearchQuery, build_api_filters, parse, query_to_field_strings


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
            {'assigned_to_id': {'operator': '=', 'values': ['5']}}
        ]

    def test_assignee_resolves_group_name(self) -> None:
        remote = RemoteConfig(users={5: 'Max'}, groups={12: 'DevOps'})
        q = SearchQuery(filters={'assignee': ['DevOps']})
        assert build_api_filters(q, remote) == [
            {'assigned_to_id': {'operator': '=', 'values': ['12']}}
        ]

    def test_assignee_mix_user_and_group(self) -> None:
        remote = RemoteConfig(users={5: 'Max'}, groups={12: 'DevOps'})
        q = SearchQuery(filters={'assignee': ['Max', 'DevOps']})
        result = build_api_filters(q, remote)
        assert result == [
            {'assigned_to_id': {'operator': '=', 'values': ['5', '12']}}
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


class TestQueryToFieldStrings:
    def test_empty_query_gives_empty_strings(self) -> None:
        result = query_to_field_strings(SearchQuery())
        assert result['words'] == ''
        assert result['status'] == ''
        assert result['type'] == ''
        assert result['priority'] == ''
        assert result['project'] == ''
        assert result['assignee'] == ''

    def test_multi_value_filter_comma_joined(self) -> None:
        q = SearchQuery(filters={'type': ['Task', 'Bug']})
        result = query_to_field_strings(q)
        assert result['type'] == 'Task, Bug'

    def test_words_are_space_joined(self) -> None:
        q = SearchQuery(words=['deploy', 'bug'])
        result = query_to_field_strings(q)
        assert result['words'] == 'deploy bug'

    def test_combined(self) -> None:
        q = SearchQuery(
            words=['hello'],
            filters={'status': ['open'], 'type': ['Task', 'Bug'], 'assignee': ['Max']},
        )
        result = query_to_field_strings(q)
        assert result['words'] == 'hello'
        assert result['status'] == 'open'
        assert result['type'] == 'Task, Bug'
        assert result['assignee'] == 'Max'


class TestParseFromFieldStrings:
    """The inverse: field strings → SearchQuery via the existing parse() function."""

    def test_parse_roundtrip(self) -> None:
        # User enters words + filters in a dialog, we reconstruct tokens and parse
        words = 'deploy bug'
        filters = {'status': 'open', 'type': 'Task, Bug'}
        tokens = words.split() + [f'{k}={v}' for k, v in filters.items()]
        q = parse(tokens)
        assert q.words == ['deploy', 'bug']
        assert q.filters == {'status': ['open'], 'type': ['Task', 'Bug']}


class TestFuzzyMatch:
    def test_unique_substring_match_is_accepted(self) -> None:
        """'nmo' uniquely matches 'Niklas Moschuring nmo' — should resolve."""
        remote = RemoteConfig(users={
            5: 'Niklas Moschuring nmo',
            6: 'Anna Moller amo',
        })
        q = SearchQuery(filters={'assignee': ['nmo']})
        assert build_api_filters(q, remote) == [
            {'assigned_to_id': {'operator': '=', 'values': ['5']}}
        ]

    def test_fuzzy_match_is_case_insensitive(self) -> None:
        remote = RemoteConfig(users={5: 'Daniel Kuhnert dku'})
        q = SearchQuery(filters={'assignee': ['DKU']})
        assert build_api_filters(q, remote) == [
            {'assigned_to_id': {'operator': '=', 'values': ['5']}}
        ]

    def test_exact_match_wins_over_substring(self) -> None:
        """If there's a literal match, it must win even if substrings also exist."""
        remote = RemoteConfig(statuses={1: 'Neu', 2: 'Neue Idee'})
        q = SearchQuery(filters={'status': ['Neu']})
        assert build_api_filters(q, remote) == [
            {'status_id': {'operator': '=', 'values': ['1']}}
        ]

    def test_ambiguous_substring_raises_with_candidate_list(self) -> None:
        remote = RemoteConfig(users={
            1: 'Admins',
            2: 'Admins priorisiert',
            3: 'Admins unpriorisiert',
        })
        q = SearchQuery(filters={'assignee': ['admin']})
        with pytest.raises(ValueError) as excinfo:
            build_api_filters(q, remote)
        msg = str(excinfo.value)
        assert 'admin' in msg.lower()
        assert 'Admins priorisiert' in msg
        assert 'Admins unpriorisiert' in msg
        # The raw "Admins" entry is also a candidate
        assert 'Admins' in msg

    def test_no_match_at_all_still_raises_unknown(self) -> None:
        remote = RemoteConfig(users={1: 'Max'})
        q = SearchQuery(filters={'assignee': ['nonexistent']})
        with pytest.raises(ValueError, match='Unknown assignee value'):
            build_api_filters(q, remote)

    def test_multiple_values_each_resolved_individually(self) -> None:
        remote = RemoteConfig(users={
            5: 'Niklas Moschuring nmo',
            6: 'Daniel Kuhnert dku',
            7: 'Alexander Prodanov apr',
        })
        q = SearchQuery(filters={'assignee': ['nmo', 'dku', 'apr']})
        result = build_api_filters(q, remote)
        assert result == [
            {'assigned_to_id': {'operator': '=', 'values': ['5', '6', '7']}}
        ]

    def test_fuzzy_match_logs_resolved_name(self, caplog) -> None:  # noqa: ANN001
        import logging
        # setup_logging from prior tests may have set op.propagate=False, which
        # blocks caplog — re-enable propagation just for this test.
        logging.getLogger('op').propagate = True
        caplog.set_level(logging.INFO, logger='op.search')
        remote = RemoteConfig(users={5: 'Niklas Moschuring nmo'})
        q = SearchQuery(filters={'assignee': ['nmo']})
        build_api_filters(q, remote)
        text = '\n'.join(r.message for r in caplog.records)
        assert 'nmo' in text
        assert 'Niklas Moschuring nmo' in text


class TestWatcherFilter:
    def test_watcher_filter_resolved(self) -> None:
        remote = RemoteConfig(users={5: 'Alice Muster'})
        q = parse(['watcher=alice'])
        filters = build_api_filters(q, remote)
        assert {'watcher_id': {'operator': '=', 'values': ['5']}} in filters

    def test_unknown_watcher_raises(self) -> None:
        remote = RemoteConfig(users={5: 'Alice'})
        q = parse(['watcher=nobody'])
        with pytest.raises(ValueError, match='watcher'):
            build_api_filters(q, remote)

    def test_watcher_field_in_query_to_field_strings(self) -> None:
        q = SearchQuery(filters={'watcher': ['alice']})
        result = query_to_field_strings(q)
        assert result['watcher'] == 'alice'


class TestPmFilter:
    def test_pm_filter_resolves_from_pm_users(self) -> None:
        """pm= looks up only in custom_field_users[42], not all users."""
        remote = RemoteConfig(custom_field_users={42: {94: 'AUM Mustermann', 5: 'Bob'}})
        q = parse(['pm=AUM'])
        filters = build_api_filters(q, remote)
        assert {'customField42': {'operator': '=', 'values': ['94']}} in filters

    def test_pm_filter_substring_match(self) -> None:
        remote = RemoteConfig(custom_field_users={42: {94: 'AUM Mustermann', 5: 'Alice'}})
        q = parse(['pm=mustermann'])
        filters = build_api_filters(q, remote)
        assert {'customField42': {'operator': '=', 'values': ['94']}} in filters

    def test_pm_filter_does_not_accept_non_pm_users(self) -> None:
        """Users not in custom_field_users[42] must not be accepted — they cause API 400."""
        remote = RemoteConfig(
            users={99: 'Fremder Nutzer'},
            custom_field_users={42: {94: 'AUM Mustermann'}},
        )
        q = parse(['pm=Fremder'])
        with pytest.raises(ValueError, match='pm'):
            build_api_filters(q, remote)

    def test_unknown_pm_raises(self) -> None:
        remote = RemoteConfig(custom_field_users={42: {94: 'AUM Mustermann'}})
        q = parse(['pm=nobody'])
        with pytest.raises(ValueError, match='pm'):
            build_api_filters(q, remote)

    def test_pm_raises_when_not_loaded(self) -> None:
        """Empty pm_users (--load-remote-data not run) → clear error."""
        remote = RemoteConfig()
        q = parse(['pm=AUM'])
        with pytest.raises(ValueError, match='pm'):
            build_api_filters(q, remote)

    def test_pm_field_in_query_to_field_strings(self) -> None:
        q = SearchQuery(filters={'pm': ['AUM']})
        result = query_to_field_strings(q)
        assert result['pm'] == 'AUM'


class TestCfNFilter:
    """Generischer cf<N>=<Wert>-Filter für Custom Fields."""

    def test_list_cf_resolves_option_by_name(self) -> None:
        remote = RemoteConfig(custom_field_options={7: {17: 'Premium', 18: 'Standard'}})
        q = parse(['cf7=Premium'])
        filters = build_api_filters(q, remote)
        assert {'customField7': {'operator': '=', 'values': ['17']}} in filters

    def test_list_cf_substring_match(self) -> None:
        remote = RemoteConfig(custom_field_options={7: {17: 'Premium', 18: 'Standard'}})
        q = parse(['cf7=prem'])
        filters = build_api_filters(q, remote)
        assert {'customField7': {'operator': '=', 'values': ['17']}} in filters

    def test_list_cf_ambiguous_raises(self) -> None:
        remote = RemoteConfig(custom_field_options={7: {17: 'Premi A', 18: 'Premi B'}})
        q = parse(['cf7=Premi'])
        with pytest.raises(ValueError, match='Ambiguous'):
            build_api_filters(q, remote)

    def test_list_cf_unknown_value_raises(self) -> None:
        remote = RemoteConfig(custom_field_options={7: {17: 'Premium'}})
        q = parse(['cf7=Unbekannt'])
        with pytest.raises(ValueError, match='cf7'):
            build_api_filters(q, remote)

    def test_list_cf_not_loaded_raises(self) -> None:
        remote = RemoteConfig()
        q = parse(['cf7=Premium'])
        with pytest.raises(ValueError, match='cf7'):
            build_api_filters(q, remote)

    def test_user_cf_resolves_by_name_via_cfn(self) -> None:
        remote = RemoteConfig(custom_field_users={42: {94: 'AUM Mustermann', 5: 'Bob'}})
        q = parse(['cf42=AUM'])
        filters = build_api_filters(q, remote)
        assert {'customField42': {'operator': '=', 'values': ['94']}} in filters

    def test_cf_filter_merges_users_and_options(self) -> None:
        """Falls ein CF sowohl Users als auch Options hat (unwahrscheinlich, aber sicher behandeln)."""
        remote = RemoteConfig(
            custom_field_users={7: {5: 'Max'}},
            custom_field_options={7: {17: 'Premium'}},
        )
        q = parse(['cf7=Premium'])
        filters = build_api_filters(q, remote)
        assert {'customField7': {'operator': '=', 'values': ['17']}} in filters

    def test_cf_filter_unknown_key_raises_helpful_message(self) -> None:
        remote = RemoteConfig()
        q = parse(['xyz=foo'])
        with pytest.raises(ValueError, match='cf<N>'):
            build_api_filters(q, remote)
