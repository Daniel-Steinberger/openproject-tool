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
