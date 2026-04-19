from __future__ import annotations

from datetime import date

import pytest

from op.models import (
    Activity,
    CustomField,
    Priority,
    Project,
    Status,
    User,
    WorkPackage,
    WorkPackageType,
)


class TestSimpleLookups:
    def test_status(self) -> None:
        s = Status(id=1, name='In Bearbeitung')
        assert s.id == 1
        assert s.name == 'In Bearbeitung'

    def test_work_package_type(self) -> None:
        t = WorkPackageType(id=2, name='Bug')
        assert t.id == 2
        assert t.name == 'Bug'

    def test_project(self) -> None:
        p = Project(id=10, name='Webportal', identifier='webportal')
        assert p.id == 10
        assert p.identifier == 'webportal'

    def test_priority(self) -> None:
        p = Priority(id=8, name='Normal')
        assert p.name == 'Normal'

    def test_user(self) -> None:
        u = User(id=5, name='Max Mustermann', login='mm', email='mm@example.com')
        assert u.login == 'mm'
        assert u.email == 'mm@example.com'

    def test_user_without_optional_fields(self) -> None:
        u = User(id=5, name='Max')
        assert u.login is None
        assert u.email is None

    def test_custom_field(self) -> None:
        cf = CustomField(id=3, name='Story Points', field_format='int')
        assert cf.field_format == 'int'


class TestWorkPackage:
    def test_minimal(self) -> None:
        wp = WorkPackage(
            id=1234,
            subject='Testtask',
            type_id=1,
            type_name='Task',
            status_id=1,
            status_name='Neu',
            project_id=10,
            project_name='Projekt',
            lock_version=3,
        )
        assert wp.id == 1234
        assert wp.subject == 'Testtask'
        assert wp.description is None
        assert wp.assignee_id is None
        assert wp.custom_fields == {}

    def test_with_optional_fields(self) -> None:
        wp = WorkPackage(
            id=1234,
            subject='Testtask',
            description='Details',
            type_id=1,
            type_name='Task',
            status_id=1,
            status_name='Neu',
            project_id=10,
            project_name='Projekt',
            priority_id=8,
            priority_name='Normal',
            assignee_id=5,
            assignee_name='Max Mustermann',
            author_id=7,
            author_name='Dev',
            start_date=date(2026, 1, 1),
            due_date=date(2026, 1, 31),
            lock_version=3,
            custom_fields={'customField3': 13},
        )
        assert wp.description == 'Details'
        assert wp.start_date == date(2026, 1, 1)
        assert wp.custom_fields == {'customField3': 13}


class TestFromApi:
    def test_status_from_api(self) -> None:
        payload = {'id': 1, 'name': 'Neu', '_type': 'Status'}
        assert Status.from_api(payload) == Status(id=1, name='Neu')

    def test_user_from_api(self) -> None:
        payload = {
            '_type': 'User',
            'id': 5,
            'name': 'Max Mustermann',
            'login': 'mm',
            'email': 'mm@example.com',
        }
        u = User.from_api(payload)
        assert u.id == 5
        assert u.login == 'mm'
        assert u.email == 'mm@example.com'

    def test_project_from_api(self) -> None:
        payload = {'_type': 'Project', 'id': 10, 'name': 'Webportal', 'identifier': 'webportal'}
        assert Project.from_api(payload).identifier == 'webportal'

    def test_custom_field_from_api(self) -> None:
        payload = {
            '_type': 'CustomOption',
            'id': 3,
            'name': 'Story Points',
            'fieldFormat': 'int',
        }
        cf = CustomField.from_api(payload)
        assert cf.field_format == 'int'

    def test_work_package_from_api(self) -> None:
        payload = {
            '_type': 'WorkPackage',
            'id': 1234,
            'subject': 'Deployment-Pipeline',
            'description': {'raw': 'Details', 'format': 'markdown', 'html': '<p>Details</p>'},
            'lockVersion': 3,
            'startDate': '2026-01-01',
            'dueDate': None,
            'customField5': 'Produktion',
            '_links': {
                'self': {'href': '/api/v3/work_packages/1234'},
                'type': {'href': '/api/v3/types/1', 'title': 'Task'},
                'status': {'href': '/api/v3/statuses/1', 'title': 'Neu'},
                'project': {'href': '/api/v3/projects/10', 'title': 'Projekt'},
                'assignee': {'href': '/api/v3/users/5', 'title': 'Max Mustermann'},
                'priority': {'href': '/api/v3/priorities/8', 'title': 'Normal'},
                'author': {'href': '/api/v3/users/7', 'title': 'Dev'},
            },
        }
        wp = WorkPackage.from_api(payload)
        assert wp.id == 1234
        assert wp.subject == 'Deployment-Pipeline'
        assert wp.description == 'Details'
        assert wp.type_id == 1
        assert wp.type_name == 'Task'
        assert wp.status_id == 1
        assert wp.status_name == 'Neu'
        assert wp.project_id == 10
        assert wp.project_name == 'Projekt'
        assert wp.assignee_id == 5
        assert wp.assignee_name == 'Max Mustermann'
        assert wp.priority_id == 8
        assert wp.priority_name == 'Normal'
        assert wp.author_id == 7
        assert wp.start_date == date(2026, 1, 1)
        assert wp.due_date is None
        assert wp.lock_version == 3
        assert wp.custom_fields == {'customField5': 'Produktion'}

    def test_work_package_from_api_unassigned(self) -> None:
        payload = {
            '_type': 'WorkPackage',
            'id': 1,
            'subject': 'Ohne Zuweisung',
            'description': {'raw': ''},
            'lockVersion': 1,
            '_links': {
                'type': {'href': '/api/v3/types/1', 'title': 'Task'},
                'status': {'href': '/api/v3/statuses/1', 'title': 'Neu'},
                'project': {'href': '/api/v3/projects/10', 'title': 'Projekt'},
                'assignee': {'href': None},
                'priority': {'href': None},
                'author': {'href': '/api/v3/users/7', 'title': 'Dev'},
            },
        }
        wp = WorkPackage.from_api(payload)
        assert wp.assignee_id is None
        assert wp.assignee_name is None
        assert wp.priority_id is None
        assert wp.description is None


class TestActivity:
    def test_from_api_with_comment(self) -> None:
        payload = {
            '_type': 'Activity::Comment',
            'id': 77,
            'createdAt': '2026-01-01T10:00:00Z',
            'comment': {'raw': 'Ein Kommentar'},
            '_links': {'user': {'href': '/api/v3/users/5', 'title': 'Max'}},
        }
        a = Activity.from_api(payload)
        assert a.id == 77
        assert a.comment == 'Ein Kommentar'
        assert a.user_name == 'Max'
        assert a.created_at == '2026-01-01T10:00:00Z'

    def test_from_api_without_comment(self) -> None:
        payload = {
            '_type': 'Activity',
            'id': 78,
            'createdAt': '2026-01-02T10:00:00Z',
            'comment': {'raw': ''},
            '_links': {'user': {'href': '/api/v3/users/5', 'title': 'Max'}},
        }
        a = Activity.from_api(payload)
        assert a.comment is None


class TestIdExtraction:
    @pytest.mark.parametrize(
        'href,expected',
        [
            ('/api/v3/statuses/1', 1),
            ('/api/v3/work_packages/12345', 12345),
            ('/api/v3/users/5', 5),
            (None, None),
            ('', None),
        ],
    )
    def test_id_from_href(self, href: str | None, expected: int | None) -> None:
        from op.models import id_from_href

        assert id_from_href(href) == expected
