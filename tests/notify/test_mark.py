from __future__ import annotations

import pytest

from op.api import OpenProjectError
from op.notify.analysis import GroupAnalysis
from op.notify.mark import MarkQueue, select_analyses


def _analysis(wp_id: int, classification: str, notification_ids: list[int]) -> GroupAnalysis:
    return GroupAnalysis(
        work_package_id=wp_id, title=f'WP {wp_id}', classification=classification,
        summary='S', notification_ids=notification_ids,
    )


def _analyses() -> list[GroupAnalysis]:
    failed = _analysis(300, 'worth_knowing', [5])
    failed.error = 'model unreachable'
    return [
        _analysis(100, 'relevant', [1, 2]),
        _analysis(200, 'churn', [3, 4]),
        failed,
    ]


class TestSelectAnalyses:
    def test_by_work_package_id(self) -> None:
        selected = select_analyses(_analyses(), work_package_ids=[200])
        assert [a.work_package_id for a in selected] == [200]

    def test_by_notification_id(self) -> None:
        """A number the user passes may be either — notification ids are matched too."""
        selected = select_analyses(_analyses(), work_package_ids=[2])
        assert [a.work_package_id for a in selected] == [100]

    def test_work_package_id_wins_over_notification_id(self) -> None:
        analyses = [_analysis(100, 'relevant', [200]), _analysis(200, 'churn', [7])]
        selected = select_analyses(analyses, work_package_ids=[200])
        assert [a.work_package_id for a in selected] == [200]

    def test_unknown_id_is_reported(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            select_analyses(_analyses(), work_package_ids=[999])
        assert '999' in str(excinfo.value)

    def test_churn_only(self) -> None:
        selected = select_analyses(_analyses(), churn=True)
        assert [a.work_package_id for a in selected] == [200]

    def test_churn_excludes_failed_analyses(self) -> None:
        analyses = _analyses()
        analyses[2].classification = 'churn'  # classification set, but analysis failed
        assert [a.work_package_id for a in select_analyses(analyses, churn=True)] == [200]

    def test_all(self) -> None:
        selected = select_analyses(_analyses(), all_groups=True)
        assert [a.work_package_id for a in selected] == [100, 200, 300]

    def test_nothing_selected_without_criteria(self) -> None:
        assert select_analyses(_analyses()) == []


class FakeClient:
    def __init__(self, *, fail_for: set[int] | None = None) -> None:
        self.marked: list[int] = []
        self.fail_for = fail_for or set()

    async def mark_read(self, notification_id: int) -> None:
        if notification_id in self.fail_for:
            raise OpenProjectError(f'boom {notification_id}')
        self.marked.append(notification_id)


class TestMarkQueue:
    def test_collects_notification_ids_without_duplicates(self) -> None:
        queue = MarkQueue()
        queue.add(_analysis(100, 'churn', [1, 2]))
        queue.add(_analysis(100, 'churn', [2, 3]))
        assert queue.notification_ids == [1, 2, 3]
        assert queue.count == 1  # one work package

    def test_remove_by_work_package(self) -> None:
        queue = MarkQueue()
        queue.add(_analysis(100, 'churn', [1]))
        queue.add(_analysis(200, 'churn', [2]))
        queue.remove(100)
        assert queue.notification_ids == [2]

    async def test_apply_marks_every_notification(self) -> None:
        queue = MarkQueue()
        queue.add(_analysis(100, 'churn', [1, 2]))
        queue.add(_analysis(200, 'churn', [3]))
        client = FakeClient()
        result = await queue.apply(client)
        assert sorted(client.marked) == [1, 2, 3]
        assert result.marked == 3
        assert result.failed == []

    async def test_failure_of_one_does_not_stop_the_rest(self) -> None:
        queue = MarkQueue()
        queue.add(_analysis(100, 'churn', [1, 2, 3]))
        client = FakeClient(fail_for={2})
        result = await queue.apply(client)
        assert sorted(client.marked) == [1, 3]
        assert result.marked == 2
        assert [nid for nid, _ in result.failed] == [2]

    async def test_progress_callback_reports_each_step(self) -> None:
        queue = MarkQueue()
        queue.add(_analysis(100, 'churn', [1, 2]))
        seen: list[tuple[int, int]] = []
        await queue.apply(FakeClient(), on_progress=lambda done, total: seen.append((done, total)))
        assert seen == [(1, 2), (2, 2)]

    async def test_empty_queue_applies_cleanly(self) -> None:
        result = await MarkQueue().apply(FakeClient())
        assert result.marked == 0
        assert result.failed == []
