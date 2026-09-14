from __future__ import annotations

import typing as T
from pathlib import Path

import pytest

from op.models import Activity, WorkPackage
from op.notify.analysis import GroupAnalysis, analyse_groups, build_report
from op.notify.cache import AnalysisCache
from op.notify.grouping import group_by_work_package
from op.notify.llm import LlmError
from op.notify.models import Notification, NotificationGroup

from .test_models import notification_payload


def _groups(*wp_ids: int) -> list[NotificationGroup]:
    return group_by_work_package([
        Notification.from_api(notification_payload(
            notif_id=i + 1, wp_id=wp_id, activity_id=100 + i,
            created_at=f'2026-09-{10 + i:02d}T10:00:00Z'))
        for i, wp_id in enumerate(wp_ids)
    ])


class FakeOp:
    """Minimal stand-in for the OpenProject client."""

    def __init__(self, *, fail_for: set[int] | None = None) -> None:
        self.fail_for = fail_for or set()
        self.work_package_calls: list[int] = []

    async def get_work_package(self, wp_id: int) -> WorkPackage | None:
        self.work_package_calls.append(wp_id)
        if wp_id in self.fail_for:
            return None
        return WorkPackage.from_api({
            'id': wp_id, 'subject': f'WP {wp_id}', 'lockVersion': 1,
            '_links': {
                'type': {'href': '/api/v3/types/1', 'title': 'Task'},
                'status': {'href': '/api/v3/statuses/1', 'title': 'Neu'},
                'project': {'href': '/api/v3/projects/1', 'title': 'P'},
            },
        })

    async def get_activities(self, wp_id: int) -> list[Activity]:
        return [Activity.from_api({
            'id': 100 + (wp_id % 10),
            'createdAt': '2026-09-10T10:00:00Z',
            'comment': {'raw': f'Kommentar zu {wp_id}'},
            'details': [],
            '_links': {'user': {'href': '/api/v3/users/16', 'title': 'Bea'}},
        })]


class FakeLlm:
    def __init__(self, *, answer: dict | None = None, fail: bool = False) -> None:
        self.answer = answer or {
            'classification': 'churn', 'title': 'T', 'summary': 'S',
            'open_points': [], 'waits_for_me': False, 'rationale': 'R',
        }
        self.fail = fail
        self.calls: list[tuple[str, str]] = []
        self.model = 'fake-model'

    async def complete_json(self, *, system: str, user: str, schema: dict, **_: T.Any) -> dict:
        self.calls.append((system, user))
        if self.fail:
            raise LlmError('model said no')
        return dict(self.answer)

    async def complete_text(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        if self.fail:
            raise LlmError('model said no')
        return '## Bericht'


class TestAnalyseGroups:
    async def test_one_analysis_per_group(self, tmp_path: Path) -> None:
        llm = FakeLlm()
        result = await analyse_groups(
            _groups(100, 200), op=FakeOp(), llm=llm, user_name='Dana',
            cache=AnalysisCache(directory=tmp_path, enabled=False),
        )
        assert [a.work_package_id for a in result] == [200, 100]  # newest group first
        assert len(llm.calls) == 2
        assert all(a.classification == 'churn' for a in result)

    async def test_activity_block_reaches_the_prompt(self, tmp_path: Path) -> None:
        llm = FakeLlm()
        await analyse_groups(
            _groups(100), op=FakeOp(), llm=llm, user_name='Dana',
            cache=AnalysisCache(directory=tmp_path, enabled=False),
        )
        _, user_prompt = llm.calls[0]
        assert 'Kommentar zu 100' in user_prompt
        assert '<activity_block>' in user_prompt

    async def test_failing_group_does_not_sink_the_run(self, tmp_path: Path) -> None:
        class HalfBrokenLlm(FakeLlm):
            async def complete_json(self, *, system: str, user: str, schema: dict, **kw) -> dict:
                self.calls.append((system, user))
                if '200' in user:
                    raise LlmError('nope')
                return dict(self.answer)

        result = await analyse_groups(
            _groups(100, 200), op=FakeOp(), llm=HalfBrokenLlm(), user_name='Dana',
            cache=AnalysisCache(directory=tmp_path, enabled=False),
        )
        failed = [a for a in result if a.error]
        assert len(failed) == 1
        assert failed[0].work_package_id == 200
        assert len([a for a in result if not a.error]) == 1

    async def test_failed_group_is_never_classified_as_churn(self, tmp_path: Path) -> None:
        """Otherwise --mark-read-churn would silently clear what was never read."""
        result = await analyse_groups(
            _groups(100), op=FakeOp(), llm=FakeLlm(fail=True), user_name='Dana',
            cache=AnalysisCache(directory=tmp_path, enabled=False),
        )
        assert result[0].classification != 'churn'
        assert result[0].error

    async def test_cache_hit_skips_the_model(self, tmp_path: Path) -> None:
        cache = AnalysisCache(directory=tmp_path)
        groups = _groups(100)
        llm = FakeLlm()
        first = await analyse_groups(groups, op=FakeOp(), llm=llm, user_name='Dana', cache=cache)
        second = await analyse_groups(groups, op=FakeOp(), llm=llm, user_name='Dana', cache=cache)
        assert len(llm.calls) == 1
        assert first[0].summary == second[0].summary
        assert second[0].cached is True

    async def test_failures_are_not_cached(self, tmp_path: Path) -> None:
        cache = AnalysisCache(directory=tmp_path)
        groups = _groups(100)
        await analyse_groups(groups, op=FakeOp(), llm=FakeLlm(fail=True),
                             user_name='Dana', cache=cache)
        llm = FakeLlm()
        result = await analyse_groups(groups, op=FakeOp(), llm=llm, user_name='Dana', cache=cache)
        assert len(llm.calls) == 1
        assert not result[0].error

    async def test_extra_instructions_are_passed_through(self, tmp_path: Path) -> None:
        llm = FakeLlm()
        await analyse_groups(
            _groups(100), op=FakeOp(), llm=llm, user_name='Dana',
            cache=AnalysisCache(directory=tmp_path, enabled=False),
            extra_instructions='Immer relevant bei Deploys.',
        )
        assert 'Immer relevant bei Deploys.' in llm.calls[0][0]

    async def test_missing_work_package_still_yields_an_analysis(self, tmp_path: Path) -> None:
        result = await analyse_groups(
            _groups(100), op=FakeOp(fail_for={100}), llm=FakeLlm(), user_name='Dana',
            cache=AnalysisCache(directory=tmp_path, enabled=False),
        )
        assert len(result) == 1
        assert result[0].work_package_id == 100

    async def test_notification_ids_are_carried_for_marking(self, tmp_path: Path) -> None:
        groups = _groups(100)
        result = await analyse_groups(
            groups, op=FakeOp(), llm=FakeLlm(), user_name='Dana',
            cache=AnalysisCache(directory=tmp_path, enabled=False),
        )
        assert result[0].notification_ids == groups[0].notification_ids

    async def test_unknown_classification_is_normalised(self, tmp_path: Path) -> None:
        llm = FakeLlm(answer={
            'classification': 'sehr wichtig', 'title': 'T', 'summary': 'S',
            'open_points': [], 'waits_for_me': True, 'rationale': 'R',
        })
        result = await analyse_groups(
            _groups(100), op=FakeOp(), llm=llm, user_name='Dana',
            cache=AnalysisCache(directory=tmp_path, enabled=False),
        )
        assert result[0].classification == 'worth_knowing'


class TestBuildReport:
    async def test_returns_model_text(self) -> None:
        analyses = [GroupAnalysis(
            work_package_id=1, title='T', classification='relevant', summary='S',
            open_points=['x'], waits_for_me=True, notification_ids=[1],
        )]
        assert await build_report(analyses, llm=FakeLlm(), user_name='Dana') == '## Bericht'

    async def test_empty_input_needs_no_model(self) -> None:
        llm = FakeLlm()
        report = await build_report([], llm=llm, user_name='Dana')
        assert llm.calls == []
        assert report.strip()

    async def test_model_failure_is_reported_not_swallowed(self) -> None:
        analyses = [GroupAnalysis(
            work_package_id=1, title='T', classification='relevant', summary='S',
            open_points=[], waits_for_me=False, notification_ids=[1],
        )]
        with pytest.raises(LlmError):
            await build_report(analyses, llm=FakeLlm(fail=True), user_name='Dana')


class TestTitleComesFromTheApi:
    async def test_group_title_wins(self, tmp_path: Path) -> None:
        llm = FakeLlm(answer={
            'classification': 'churn', 'summary': 'S', 'open_points': [],
            'waits_for_me': False, 'rationale': 'R',
            'title': '## Work package #100 — vom Modell erfunden',
        })
        result = await analyse_groups(
            _groups(100), op=FakeOp(), llm=llm, user_name='Dana',
            cache=AnalysisCache(directory=tmp_path, enabled=False),
        )
        assert result[0].title == _groups(100)[0].title
        assert 'Work package' not in result[0].title
