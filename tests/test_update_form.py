from __future__ import annotations

from op.tui.update_form import UpdateForm


class TestEmptyForm:
    def test_no_changes_by_default(self) -> None:
        form = UpdateForm()
        assert not form.has_changes
        assert form.api_changes() == {}


class TestStatus:
    def test_set_status(self) -> None:
        form = UpdateForm()
        form.status_id = 5
        assert form.has_changes
        assert form.api_changes() == {
            '_links': {'status': {'href': '/api/v3/statuses/5'}}
        }

    def test_clear_status(self) -> None:
        form = UpdateForm()
        form.status_id = 5
        form.status_id = None
        assert not form.has_changes


class TestType:
    def test_set_type(self) -> None:
        form = UpdateForm()
        form.type_id = 2
        assert form.api_changes() == {'_links': {'type': {'href': '/api/v3/types/2'}}}


class TestPriority:
    def test_set_priority(self) -> None:
        form = UpdateForm()
        form.priority_id = 9
        assert form.api_changes() == {
            '_links': {'priority': {'href': '/api/v3/priorities/9'}}
        }


class TestAssignee:
    def test_set_assignee(self) -> None:
        form = UpdateForm()
        form.assignee_id = 5
        assert form.api_changes() == {
            '_links': {'assignee': {'href': '/api/v3/users/5'}}
        }

    def test_unassign_sets_href_none(self) -> None:
        form = UpdateForm()
        form.unassign = True
        assert form.api_changes() == {'_links': {'assignee': {'href': None}}}

    def test_cannot_set_both_assignee_and_unassign(self) -> None:
        form = UpdateForm()
        form.unassign = True
        form.assignee_id = 5
        # Setting assignee_id should clear unassign flag.
        assert form.unassign is False
        assert form.api_changes() == {
            '_links': {'assignee': {'href': '/api/v3/users/5'}}
        }


class TestScalarFields:
    def test_set_subject(self) -> None:
        form = UpdateForm()
        form.subject = 'Neuer Titel'
        assert form.api_changes() == {'subject': 'Neuer Titel'}

    def test_set_description(self) -> None:
        form = UpdateForm()
        form.description = 'Ausführlicher Text'
        assert form.api_changes() == {
            'description': {'raw': 'Ausführlicher Text', 'format': 'markdown'}
        }

    def test_set_start_date(self) -> None:
        form = UpdateForm()
        form.start_date = '2026-05-01'
        assert form.api_changes() == {'startDate': '2026-05-01'}

    def test_set_due_date(self) -> None:
        form = UpdateForm()
        form.due_date = '2026-05-31'
        assert form.api_changes() == {'dueDate': '2026-05-31'}

    def test_empty_string_clears_subject(self) -> None:
        form = UpdateForm()
        form.subject = 'abc'
        form.subject = ''
        assert form.api_changes() == {}

    def test_all_scalar_and_link_fields_together(self) -> None:
        form = UpdateForm()
        form.status_id = 2
        form.subject = 'T'
        form.description = 'Desc'
        form.start_date = '2026-01-01'
        changes = form.api_changes()
        assert changes['subject'] == 'T'
        assert changes['description'] == {'raw': 'Desc', 'format': 'markdown'}
        assert changes['startDate'] == '2026-01-01'
        assert changes['_links']['status'] == {'href': '/api/v3/statuses/2'}


class TestGroupAssignee:
    def test_assignee_as_group_uses_group_url(self) -> None:
        form = UpdateForm()
        form.set_assignee(principal_id=12, is_group=True)
        assert form.api_changes() == {
            '_links': {'assignee': {'href': '/api/v3/groups/12'}}
        }

    def test_assignee_as_user_still_uses_user_url(self) -> None:
        form = UpdateForm()
        form.set_assignee(principal_id=5, is_group=False)
        assert form.api_changes() == {
            '_links': {'assignee': {'href': '/api/v3/users/5'}}
        }

    def test_setter_shortcut_defaults_to_user(self) -> None:
        form = UpdateForm()
        form.assignee_id = 5
        assert form.api_changes() == {
            '_links': {'assignee': {'href': '/api/v3/users/5'}}
        }


class TestProject:
    def test_set_project(self) -> None:
        form = UpdateForm()
        form.project_id = 10
        assert form.has_changes
        assert form.api_changes() == {
            '_links': {'project': {'href': '/api/v3/projects/10'}}
        }

    def test_clear_project(self) -> None:
        form = UpdateForm()
        form.project_id = 10
        form.project_id = None
        assert not form.has_changes

    def test_project_combined_with_other_links(self) -> None:
        form = UpdateForm()
        form.status_id = 2
        form.project_id = 5
        assert form.api_changes() == {
            '_links': {
                'status': {'href': '/api/v3/statuses/2'},
                'project': {'href': '/api/v3/projects/5'},
            }
        }

    def test_project_in_summary(self) -> None:
        form = UpdateForm()
        form.project_id = 10
        summary = form.summary(projects={10: 'WebPortal'})
        assert 'WebPortal' in summary


class TestWatchers:
    def test_add_watcher_tracks_id(self) -> None:
        form = UpdateForm()
        form.add_watcher(5)
        assert 5 in form.add_watcher_ids

    def test_remove_watcher_tracks_id(self) -> None:
        form = UpdateForm()
        form.remove_watcher(6)
        assert 6 in form.remove_watcher_ids

    def test_add_watcher_dedup(self) -> None:
        form = UpdateForm()
        form.add_watcher(5)
        form.add_watcher(5)
        assert form.add_watcher_ids.count(5) == 1

    def test_remove_watcher_dedup(self) -> None:
        form = UpdateForm()
        form.remove_watcher(6)
        form.remove_watcher(6)
        assert form.remove_watcher_ids.count(6) == 1

    def test_has_watcher_changes_true_when_adding(self) -> None:
        form = UpdateForm()
        form.add_watcher(5)
        assert form.has_watcher_changes
        assert form.has_changes

    def test_has_watcher_changes_true_when_removing(self) -> None:
        form = UpdateForm()
        form.remove_watcher(5)
        assert form.has_watcher_changes

    def test_has_patch_changes_false_with_only_watchers(self) -> None:
        form = UpdateForm()
        form.add_watcher(5)
        assert not form.has_patch_changes

    def test_watcher_changes_not_in_api_changes(self) -> None:
        form = UpdateForm()
        form.add_watcher(5)
        form.remove_watcher(6)
        assert form.api_changes() == {}

    def test_summary_includes_add_watcher(self) -> None:
        form = UpdateForm()
        form.add_watcher(5)
        summary = form.summary(users={5: 'Alice'})
        assert '+Alice' in summary

    def test_summary_includes_remove_watcher(self) -> None:
        form = UpdateForm()
        form.remove_watcher(6)
        summary = form.summary(users={6: 'Bob'})
        assert '-Bob' in summary

    def test_summary_uses_id_fallback_when_user_unknown(self) -> None:
        form = UpdateForm()
        form.add_watcher(99)
        summary = form.summary()
        assert '#99' in summary

    def test_merge_from_accumulates_add_watchers(self) -> None:
        form1 = UpdateForm()
        form1.add_watcher(5)
        form2 = UpdateForm()
        form2.add_watcher(6)
        form1.merge_from(form2)
        assert set(form1.add_watcher_ids) == {5, 6}

    def test_merge_from_deduplicates_add_watchers(self) -> None:
        form1 = UpdateForm()
        form1.add_watcher(5)
        form2 = UpdateForm()
        form2.add_watcher(5)
        form1.merge_from(form2)
        assert form1.add_watcher_ids.count(5) == 1

    def test_merge_from_accumulates_remove_watchers(self) -> None:
        form1 = UpdateForm()
        form1.remove_watcher(5)
        form2 = UpdateForm()
        form2.remove_watcher(6)
        form1.merge_from(form2)
        assert set(form1.remove_watcher_ids) == {5, 6}

    def test_empty_form_has_no_watcher_changes(self) -> None:
        form = UpdateForm()
        assert not form.has_watcher_changes
        assert form.add_watcher_ids == []
        assert form.remove_watcher_ids == []


class TestCustomFieldUser:
    def test_set_custom_field_user_appears_in_api_changes(self) -> None:
        form = UpdateForm()
        form.set_custom_field_user(4, 1)
        assert form.api_changes() == {
            '_links': {'customField4': {'href': '/api/v3/users/1'}}
        }

    def test_clear_custom_field_user_sends_null_href(self) -> None:
        form = UpdateForm()
        form.set_custom_field_user(4, None)
        assert form.api_changes() == {
            '_links': {'customField4': {'href': None}}
        }

    def test_custom_field_user_has_changes(self) -> None:
        form = UpdateForm()
        form.set_custom_field_user(4, 1)
        assert form.has_changes
        assert form.has_patch_changes

    def test_no_custom_field_changes_by_default(self) -> None:
        form = UpdateForm()
        assert form.api_changes() == {}

    def test_multiple_custom_fields(self) -> None:
        form = UpdateForm()
        form.set_custom_field_user(4, 1)
        form.set_custom_field_user(7, 2)
        links = form.api_changes()['_links']
        assert links['customField4'] == {'href': '/api/v3/users/1'}
        assert links['customField7'] == {'href': '/api/v3/users/2'}

    def test_custom_field_combined_with_status(self) -> None:
        form = UpdateForm()
        form.status_id = 3
        form.set_custom_field_user(4, 5)
        links = form.api_changes()['_links']
        assert 'status' in links
        assert 'customField4' in links

    def test_merge_from_propagates_custom_field(self) -> None:
        form1 = UpdateForm()
        form2 = UpdateForm()
        form2.set_custom_field_user(4, 2)
        form1.merge_from(form2)
        assert form1.api_changes()['_links']['customField4'] == {'href': '/api/v3/users/2'}

    def test_merge_from_last_writer_wins_per_field(self) -> None:
        form1 = UpdateForm()
        form1.set_custom_field_user(4, 1)
        form2 = UpdateForm()
        form2.set_custom_field_user(4, 2)
        form1.merge_from(form2)
        assert form1.api_changes()['_links']['customField4'] == {'href': '/api/v3/users/2'}

    def test_merge_from_keeps_untouched_custom_field(self) -> None:
        form1 = UpdateForm()
        form1.set_custom_field_user(4, 1)
        form2 = UpdateForm()
        form2.status_id = 3
        form1.merge_from(form2)
        links = form1.api_changes()['_links']
        assert links['customField4'] == {'href': '/api/v3/users/1'}

    def test_summary_shows_custom_field_change(self) -> None:
        form = UpdateForm()
        form.set_custom_field_user(4, 1)
        summary = form.summary(
            custom_fields={4: 'Projektmanager'},
            users={1: 'Alice'},
        )
        assert 'Projektmanager' in summary
        assert 'Alice' in summary

    def test_summary_fallback_when_names_unknown(self) -> None:
        form = UpdateForm()
        form.set_custom_field_user(4, 99)
        summary = form.summary()
        assert 'CF#4' in summary or '#99' in summary


class TestCustomFieldOption:
    def test_set_custom_field_option_appears_in_api_changes(self) -> None:
        form = UpdateForm()
        form.set_custom_field_option(7, 17)
        assert form.api_changes() == {
            '_links': {'customField7': {'href': '/api/v3/custom_options/17'}}
        }

    def test_clear_custom_field_option_sends_null_href(self) -> None:
        form = UpdateForm()
        form.set_custom_field_option(7, None)
        assert form.api_changes() == {
            '_links': {'customField7': {'href': None}}
        }

    def test_custom_field_option_has_changes(self) -> None:
        form = UpdateForm()
        form.set_custom_field_option(7, 17)
        assert form.has_changes
        assert form.has_patch_changes

    def test_multiple_list_custom_fields(self) -> None:
        form = UpdateForm()
        form.set_custom_field_option(7, 17)
        form.set_custom_field_option(9, 20)
        links = form.api_changes()['_links']
        assert links['customField7'] == {'href': '/api/v3/custom_options/17'}
        assert links['customField9'] == {'href': '/api/v3/custom_options/20'}

    def test_list_cf_combined_with_user_cf(self) -> None:
        form = UpdateForm()
        form.set_custom_field_user(42, 5)
        form.set_custom_field_option(7, 17)
        links = form.api_changes()['_links']
        assert links['customField42'] == {'href': '/api/v3/users/5'}
        assert links['customField7'] == {'href': '/api/v3/custom_options/17'}

    def test_merge_from_propagates_option(self) -> None:
        form1 = UpdateForm()
        form2 = UpdateForm()
        form2.set_custom_field_option(7, 17)
        form1.merge_from(form2)
        assert form1.api_changes()['_links']['customField7'] == {'href': '/api/v3/custom_options/17'}

    def test_merge_from_last_writer_wins_for_option(self) -> None:
        form1 = UpdateForm()
        form1.set_custom_field_option(7, 17)
        form2 = UpdateForm()
        form2.set_custom_field_option(7, 18)
        form1.merge_from(form2)
        assert form1.api_changes()['_links']['customField7'] == {'href': '/api/v3/custom_options/18'}

    def test_summary_shows_list_cf_change(self) -> None:
        form = UpdateForm()
        form.set_custom_field_option(7, 17)
        summary = form.summary(
            custom_fields={7: 'Kundenklasse'},
            custom_field_options={7: {17: 'Premium', 18: 'Standard'}},
        )
        assert 'Kundenklasse' in summary
        assert 'Premium' in summary

    def test_summary_fallback_when_option_unknown(self) -> None:
        form = UpdateForm()
        form.set_custom_field_option(7, 99)
        summary = form.summary()
        assert 'CF#7' in summary or '#99' in summary

    def test_summary_clear_option_shows_none(self) -> None:
        form = UpdateForm()
        form.set_custom_field_option(7, None)
        summary = form.summary(
            custom_fields={7: 'Kundenklasse'},
            custom_field_options={7: {17: 'Premium'}},
        )
        assert 'Kundenklasse' in summary
        assert '(none)' in summary


class TestCombined:
    def test_all_fields_at_once(self) -> None:
        form = UpdateForm()
        form.status_id = 3
        form.type_id = 2
        form.priority_id = 9
        form.assignee_id = 5
        assert form.api_changes() == {
            '_links': {
                'status': {'href': '/api/v3/statuses/3'},
                'type': {'href': '/api/v3/types/2'},
                'priority': {'href': '/api/v3/priorities/9'},
                'assignee': {'href': '/api/v3/users/5'},
            }
        }

    def test_summary(self) -> None:
        form = UpdateForm()
        form.status_id = 3
        form.assignee_id = 5
        summary = form.summary(
            statuses={3: 'In Bearbeitung'},
            users={5: 'Max Mustermann'},
        )
        assert 'In Bearbeitung' in summary
        assert 'Max Mustermann' in summary
