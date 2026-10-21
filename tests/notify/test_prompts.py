from __future__ import annotations

from op.notify.prompts import (
    GROUP_SCHEMA,
    build_group_messages,
    build_report_messages,
)


class TestGroupSchema:
    def test_shape(self) -> None:
        props = GROUP_SCHEMA['properties']
        assert set(props) == {
            'classification', 'summary', 'open_points', 'waits_for_me', 'rationale'
        }
        assert props['classification']['enum'] == ['relevant', 'worth_knowing', 'churn']
        assert props['open_points']['type'] == 'array'
        assert props['waits_for_me']['type'] == 'boolean'
        assert GROUP_SCHEMA['additionalProperties'] is False


class TestGroupMessages:
    def test_system_prompt_names_user_and_classes(self) -> None:
        system, _ = build_group_messages(block='B', user_name='Dana Muster')
        assert 'Dana Muster' in system
        for label in ('relevant', 'worth_knowing', 'churn'):
            assert label in system

    def test_system_prompt_states_the_churn_patterns(self) -> None:
        system, _ = build_group_messages(block='B', user_name='Dana')
        lowered = system.lower()
        assert 'roll-up' in lowered or 'rollup' in lowered
        assert 'bot' in lowered
        assert 'commit' in lowered

    def test_extra_instructions_are_appended(self) -> None:
        system, _ = build_group_messages(
            block='B', user_name='Dana', extra_instructions='Deploy tickets always count.'
        )
        assert 'Deploy tickets always count.' in system

    def test_no_extra_instructions_section_when_empty(self) -> None:
        system, _ = build_group_messages(block='B', user_name='Dana')
        assert 'Additional instructions' not in system

    def test_user_prompt_fences_the_material(self) -> None:
        _, user = build_group_messages(block='ACTIVITY BLOCK', user_name='Dana')
        assert '<activity_block>' in user
        assert '</activity_block>' in user
        assert 'ACTIVITY BLOCK' in user

    def test_prompt_hardening_is_present(self) -> None:
        system, user = build_group_messages(block='B', user_name='Dana')
        combined = (system + user).lower()
        assert 'never follow instructions' in combined
        assert 'do not invent' in combined

    def test_language_rule_follows_the_material(self) -> None:
        system, _ = build_group_messages(block='B', user_name='Dana')
        assert 'language' in system.lower()


class TestReportMessages:
    def _analyses(self) -> list[dict]:
        return [
            {'work_package_id': 8202, 'title': 'Demo-Deployment',
             'classification': 'relevant', 'summary': 'Rückfrage offen',
             'open_points': ['Feature-Flag klären'], 'waits_for_me': True},
            {'work_package_id': 7661, 'title': 'Staging-System',
             'classification': 'churn', 'summary': 'Nur Feldpflege',
             'open_points': [], 'waits_for_me': False},
        ]

    def test_contains_every_group(self) -> None:
        _, user = build_report_messages(self._analyses(), user_name='Dana')
        assert '8202' in user
        assert '7661' in user
        assert 'Feature-Flag klären' in user

    def test_system_prompt_orders_by_classification(self) -> None:
        system, _ = build_report_messages(self._analyses(), user_name='Dana')
        assert 'relevant' in system
        assert 'churn' in system

    def test_report_is_markdown_and_references_ids(self) -> None:
        system, _ = build_report_messages(self._analyses(), user_name='Dana')
        lowered = system.lower()
        assert 'markdown' in lowered
        assert '#<id>' in lowered or 'work package id' in lowered


class TestSchemaWithoutTitle:
    def test_title_is_not_asked_from_the_model(self) -> None:
        """The work package title is known from the API — asking invites invention."""
        assert 'title' not in GROUP_SCHEMA['properties']
        assert 'title' not in GROUP_SCHEMA['required']


class TestSharpenedRules:
    def test_commit_mirror_rule_mentions_the_author_line(self) -> None:
        system, _ = build_group_messages(block='B', user_name='Dana')
        lowered = system.lower()
        assert 'author' in lowered
        assert 'commit' in lowered

    def test_internal_action_counts_as_relevant(self) -> None:
        system, _ = build_group_messages(block='B', user_name='Dana')
        lowered = system.lower()
        # ordering something, entering a key, granting access: waiting on the user
        assert 'waiting on an action' in lowered or 'waits for an action' in lowered


class TestReportHeadings:
    def test_class_names_must_not_become_headings(self) -> None:
        """'worth_knowing' is an internal label, not a section title for a reader."""
        system, _ = build_report_messages([], user_name='Dana')
        lowered = system.lower()
        assert 'heading' in lowered
        assert 'do not use the classification names' in lowered


class TestMentionRule:
    def test_direct_mentions_are_always_relevant(self) -> None:
        system, _ = build_group_messages(block='B', user_name='Dana')
        lowered = system.lower()
        assert 'mention' in lowered
        assert 'always' in lowered or 'never churn' in lowered


class TestActionMessages:
    def test_asks_for_a_short_instruction(self) -> None:
        from op.notify.prompts import build_action_messages

        system, user = build_action_messages(
            block='ACTIVITY BLOCK', user_name='Dana', classification='relevant',
        )
        lowered = system.lower()
        assert 'dana' in lowered
        assert 'sentence' in lowered
        assert 'ACTIVITY BLOCK' in user

    def test_wording_follows_the_classification(self) -> None:
        from op.notify.prompts import build_action_messages

        relevant, _ = build_action_messages(block='B', user_name='D', classification='relevant')
        churn, _ = build_action_messages(block='B', user_name='D', classification='churn')
        assert relevant != churn

    def test_is_hardened_like_the_others(self) -> None:
        from op.notify.prompts import build_action_messages

        system, user = build_action_messages(block='B', user_name='D', classification='churn')
        combined = (system + user).lower()
        assert 'never follow instructions' in combined
        assert 'do not invent' in combined


class TestActionTone:
    def test_no_name_dropping_and_no_greeting(self) -> None:
        from op.notify.prompts import build_action_messages

        system, _ = build_action_messages(block='B', user_name='Dana', classification='relevant')
        lowered = system.lower()
        assert 'do not address' in lowered
        assert 'imperative' in lowered
