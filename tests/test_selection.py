from __future__ import annotations

from op.tui.selection import Selection


class TestSelection:
    def test_empty_by_default(self) -> None:
        s = Selection()
        assert s.count == 0
        assert not s.contains(1)

    def test_toggle_adds_and_removes(self) -> None:
        s = Selection()
        s.toggle(1)
        assert s.contains(1)
        assert s.count == 1
        s.toggle(1)
        assert not s.contains(1)
        assert s.count == 0

    def test_toggle_multiple(self) -> None:
        s = Selection()
        for task_id in (1, 2, 3):
            s.toggle(task_id)
        assert s.count == 3
        assert all(s.contains(i) for i in (1, 2, 3))

    def test_invert_flips_all(self) -> None:
        s = Selection()
        s.toggle(1)
        s.toggle(3)
        s.invert(all_ids=[1, 2, 3, 4])
        assert not s.contains(1)
        assert s.contains(2)
        assert not s.contains(3)
        assert s.contains(4)

    def test_invert_with_no_previous_selection_selects_all(self) -> None:
        s = Selection()
        s.invert(all_ids=[1, 2, 3])
        assert s.count == 3

    def test_invert_with_all_selected_deselects_all(self) -> None:
        s = Selection()
        for task_id in (1, 2, 3):
            s.toggle(task_id)
        s.invert(all_ids=[1, 2, 3])
        assert s.count == 0

    def test_clear(self) -> None:
        s = Selection()
        s.toggle(1)
        s.toggle(2)
        s.clear()
        assert s.count == 0

    def test_as_list_is_sorted(self) -> None:
        s = Selection()
        s.toggle(3)
        s.toggle(1)
        s.toggle(2)
        assert s.as_list() == [1, 2, 3]
