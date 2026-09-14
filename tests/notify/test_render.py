from __future__ import annotations

from op.models import Activity, WorkPackage
from op.notify.grouping import group_by_work_package
from op.notify.models import Notification
from op.notify.render import clean_comment, render_group

from .test_models import notification_payload


def _group(*, activity_ids: list[int]):
    notifications = [
        Notification.from_api(notification_payload(
            notif_id=i + 1, activity_id=aid, reason='responsible',
            created_at=f'2026-09-{10 + i:02d}T10:00:00Z'))
        for i, aid in enumerate(activity_ids)
    ]
    return group_by_work_package(notifications)[0]


def _work_package() -> WorkPackage:
    return WorkPackage.from_api({
        'id': 8202,
        'subject': 'Demo-Deployment',
        'lockVersion': 1,
        '_links': {
            'type': {'href': '/api/v3/types/1', 'title': 'Task'},
            'status': {'href': '/api/v3/statuses/7', 'title': 'Fachliche Rückfrage'},
            'project': {'href': '/api/v3/projects/106', 'title': 'Sample project'},
            'assignee': {'href': '/api/v3/users/16', 'title': 'Bea Beispiel'},
            'responsible': {'href': '/api/v3/users/7', 'title': 'Dana Muster'},
        },
    })


def _activity(act_id: int, **kwargs) -> Activity:
    payload = {
        'id': act_id,
        'createdAt': kwargs.get('created_at', '2026-09-10T10:00:00Z'),
        'comment': {'raw': kwargs.get('comment', '')},
        'details': [{'raw': d} for d in kwargs.get('details', [])],
        '_links': {'user': {
            'href': f"/api/v3/users/{kwargs.get('user_id', 16)}",
            'title': kwargs.get('user_name', 'Bea Beispiel'),
        }},
    }
    return Activity.from_api(payload)


class TestCleanComment:
    def test_mention_markup_becomes_plain_handle(self) -> None:
        raw = (
            '<mention class="mention" data-id="7" data-type="user" '
            'data-text="@Dana Muster">@Dana Muster</mention> kannst Du das übernehmen?'
        )
        assert clean_comment(raw) == '@Dana Muster kannst Du das übernehmen?'

    def test_details_block_is_reduced_to_its_summary(self) -> None:
        raw = (
            '<details> <summary><a href="https://git.example.com/c/ab12"><code>ab12</code></a> '
            'Zaun: Dialog trennt zwei Felder</summary> Ein sehr langer Fließtext, der die '
            'komplette Commit-Nachricht wiederholt und im Bericht nichts beiträgt. '
            '</details>'
        )
        cleaned = clean_comment(raw)
        assert 'Zaun: Dialog trennt zwei Felder' in cleaned
        assert 'komplette Commit-Nachricht' not in cleaned

    def test_html_entities_are_decoded(self) -> None:
        assert clean_comment('a&nbsp;b &gt; c') == 'a b > c'

    def test_whitespace_is_collapsed(self) -> None:
        assert clean_comment('viel\n\n   Platz') == 'viel Platz'

    def test_empty_input(self) -> None:
        assert clean_comment('') == ''
        assert clean_comment(None) == ''


class TestRenderGroup:
    def test_header_carries_the_facts_the_model_needs(self) -> None:
        text = render_group(_group(activity_ids=[100]), _work_package(), [_activity(100)])
        assert '#8202' in text
        assert 'Demo-Deployment' in text
        assert 'Sample project' in text
        assert 'Fachliche Rückfrage' in text
        assert 'Dana Muster' in text      # responsible
        assert 'Bea Beispiel' in text     # assignee
        assert 'responsible' in text      # notification reason

    def test_only_activities_of_this_group_are_rendered(self) -> None:
        activities = [
            _activity(100, comment='gehört dazu'),
            _activity(999, comment='gehört nicht dazu'),
        ]
        text = render_group(_group(activity_ids=[100]), _work_package(), activities)
        assert 'gehört dazu' in text
        assert 'gehört nicht dazu' not in text

    def test_field_changes_are_rendered(self) -> None:
        activities = [_activity(100, details=[
            'Status geändert von **Neu** zu **In Bearbeitung**',
            'Verantwortlich wurde auf **Dana Muster** gesetzt',
        ])]
        text = render_group(_group(activity_ids=[100]), _work_package(), activities)
        assert 'Status geändert von **Neu** zu **In Bearbeitung**' in text
        assert 'Verantwortlich wurde auf **Dana Muster** gesetzt' in text

    def test_own_activities_hidden_by_default(self) -> None:
        activities = [
            _activity(100, user_id=7, user_name='Dana Muster', comment='von mir selbst'),
            _activity(101, user_id=16, comment='von jemand anderem'),
        ]
        text = render_group(
            _group(activity_ids=[100, 101]), _work_package(), activities, own_user_id=7
        )
        assert 'von mir selbst' not in text
        assert 'von jemand anderem' in text

    def test_own_activities_kept_and_marked_when_requested(self) -> None:
        activities = [_activity(100, user_id=7, user_name='Dana Muster', comment='von mir selbst')]
        text = render_group(
            _group(activity_ids=[100]), _work_package(), activities,
            own_user_id=7, hide_own=False,
        )
        assert 'von mir selbst' in text
        assert 'selbst ausgelöst' in text

    def test_note_when_every_activity_was_own(self) -> None:
        activities = [_activity(100, user_id=7, comment='nur ich')]
        text = render_group(
            _group(activity_ids=[100]), _work_package(), activities, own_user_id=7
        )
        assert 'nur ich' not in text
        assert 'eigene' in text.lower()  # the block says why it is empty

    def test_long_comments_are_truncated(self) -> None:
        activities = [_activity(100, comment='x' * 5000)]
        text = render_group(
            _group(activity_ids=[100]), _work_package(), activities, max_comment_chars=200
        )
        assert 'x' * 200 in text
        assert 'x' * 500 not in text
        assert '…' in text

    def test_works_without_work_package_details(self) -> None:
        text = render_group(_group(activity_ids=[100]), None, [_activity(100, comment='da')])
        assert 'da' in text
        assert '#8202' in text
