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
