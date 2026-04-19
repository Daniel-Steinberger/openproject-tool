from __future__ import annotations

import pytest

from op.queue import OperationQueue, PendingOperation
from op.tui.update_form import UpdateForm


class TestEmptyQueue:
    def test_count_is_zero(self) -> None:
        q = OperationQueue()
        assert q.count == 0

    def test_all_is_empty(self) -> None:
        q = OperationQueue()
        assert q.all() == []

    def test_get_missing_returns_none(self) -> None:
        q = OperationQueue()
        assert q.get(1234) is None


class TestAddOrMerge:
    def test_add_single_operation(self) -> None:
        q = OperationQueue()
        form = UpdateForm()
        form.status_id = 2
        q.add_or_merge(1234, form)
        assert q.count == 1
        op = q.get(1234)
        assert op is not None
        assert op.task_id == 1234
        assert op.form.status_id == 2

    def test_merging_second_edit_overlays_fields(self) -> None:
        """F1: Fields that overwrite each other — last write wins per field."""
        q = OperationQueue()
        first = UpdateForm()
        first.status_id = 2
        first.priority_id = 8
        q.add_or_merge(1234, first)

        second = UpdateForm()
        second.priority_id = 9  # overrides
        second.type_id = 3      # additive
        q.add_or_merge(1234, second)

        op = q.get(1234)
        assert op is not None
        assert op.form.status_id == 2    # kept from first edit
        assert op.form.priority_id == 9  # last wins
        assert op.form.type_id == 3      # added
        assert q.count == 1              # still one operation

    def test_merging_clears_assignee_if_new_unassign_set(self) -> None:
        q = OperationQueue()
        first = UpdateForm()
        first.assignee_id = 5
        q.add_or_merge(1234, first)

        second = UpdateForm()
        second.unassign = True
        q.add_or_merge(1234, second)

        op = q.get(1234)
        assert op is not None
        assert op.form.assignee_id is None
        assert op.form.unassign is True


class TestRemove:
    def test_remove_existing(self) -> None:
        q = OperationQueue()
        q.add_or_merge(1234, UpdateForm())
        q.remove(1234)
        assert q.count == 0
        assert q.get(1234) is None

    def test_remove_missing_is_noop(self) -> None:
        q = OperationQueue()
        q.remove(9999)  # must not raise
        assert q.count == 0


class TestAll:
    def test_returns_operations_in_insertion_order(self) -> None:
        q = OperationQueue()
        for task_id in (3, 1, 2):
            q.add_or_merge(task_id, UpdateForm())
        ids = [op.task_id for op in q.all()]
        assert ids == [3, 1, 2]


class TestStatusAndError:
    def test_initial_status_is_pending(self) -> None:
        q = OperationQueue()
        q.add_or_merge(1, UpdateForm())
        op = q.get(1)
        assert op.status == 'pending'
        assert op.error is None

    def test_status_can_be_updated(self) -> None:
        q = OperationQueue()
        q.add_or_merge(1, UpdateForm())
        op = q.get(1)
        op.status = 'running'
        op.status = 'failed'
        op.error = '409 lock-version conflict'
        assert q.get(1).status == 'failed'
        assert q.get(1).error == '409 lock-version conflict'


class TestClear:
    def test_clear_removes_all(self) -> None:
        q = OperationQueue()
        q.add_or_merge(1, UpdateForm())
        q.add_or_merge(2, UpdateForm())
        q.clear()
        assert q.count == 0

    def test_clear_done_keeps_failures(self) -> None:
        q = OperationQueue()
        q.add_or_merge(1, UpdateForm())
        q.add_or_merge(2, UpdateForm())
        q.get(1).status = 'done'
        q.get(2).status = 'failed'
        q.clear_done()
        assert q.count == 1
        assert q.get(1) is None
        assert q.get(2) is not None


class TestFormMerge:
    def test_merge_last_wins_per_field(self) -> None:
        base = UpdateForm()
        base.status_id = 1
        base.priority_id = 8

        other = UpdateForm()
        other.priority_id = 9
        other.subject = 'Neu'

        base.merge_from(other)
        assert base.status_id == 1
        assert base.priority_id == 9
        assert base.subject == 'Neu'

    def test_merge_does_not_clear_base_when_other_is_none(self) -> None:
        base = UpdateForm()
        base.status_id = 5

        other = UpdateForm()  # all None
        base.merge_from(other)
        assert base.status_id == 5

    def test_merge_assignee_overrides_unassign(self) -> None:
        base = UpdateForm()
        base.unassign = True

        other = UpdateForm()
        other.assignee_id = 7
        base.merge_from(other)
        assert base.assignee_id == 7
        assert base.unassign is False

    def test_merge_unassign_overrides_assignee(self) -> None:
        base = UpdateForm()
        base.assignee_id = 7

        other = UpdateForm()
        other.unassign = True
        base.merge_from(other)
        assert base.assignee_id is None
        assert base.unassign is True


class TestPendingOperationSummary:
    def test_summary_describes_fields(self) -> None:
        form = UpdateForm()
        form.status_id = 2
        form.subject = 'Hello'
        op = PendingOperation(task_id=1, form=form)
        summary = op.summary()
        assert 'Status' in summary or 'status' in summary
        assert 'Subject' in summary or 'subject' in summary

    def test_resolved_summary_uses_remote_names(self) -> None:
        form = UpdateForm()
        form.status_id = 2
        op = PendingOperation(task_id=1, form=form)
        summary = op.summary(statuses={1: 'Neu', 2: 'In Bearbeitung'})
        assert 'In Bearbeitung' in summary


@pytest.mark.parametrize('count,expected', [(0, 0), (1, 1), (5, 5)])
def test_count_tracks_add(count: int, expected: int) -> None:
    q = OperationQueue()
    for i in range(count):
        q.add_or_merge(i, UpdateForm())
    assert q.count == expected
