from __future__ import annotations

import typing as T

from op.models import WorkPackage
from op.tui.picker_widget import (
    ListPickerScreen,
    PickerWidget,
    WorkPackagePickerScreen,
)


def _wp(id: int, subject: str, type_name: str = 'Projekt') -> WorkPackage:
    return WorkPackage(
        id=id, subject=subject, type_id=10, type_name=type_name,
        status_id=1, status_name='Neu', project_id=10, project_name='Web',
        lock_version=1,
    )


class TestBlankLabel:
    def test_picker_blank_without_label(self) -> None:
        p = PickerWidget([('A', 1)], id='x')
        assert p._label_for(None) == '— no change —'

    def test_picker_blank_with_label(self) -> None:
        p = PickerWidget([('A', 1)], id='x', blank_label='Neu')
        assert p._label_for(None) == '— no change — (Neu)'

    def test_picker_selected_value_ignores_blank_label(self) -> None:
        p = PickerWidget([('A', 1)], id='x', blank_label='Neu')
        assert p._label_for(1) == 'A'

    def test_listpicker_blank_item_carries_label(self) -> None:
        s = ListPickerScreen([('A', 1)], blank_label='Hoch')
        assert s._items[0][0] == '— no change — (Hoch)'

    def test_listpicker_blank_item_without_label(self) -> None:
        s = ListPickerScreen([('A', 1)])
        assert s._items[0][0] == '— no change —'


class _FakeClient:
    def __init__(self, results: list[WorkPackage]) -> None:
        self.results = results
        self.calls: list[dict[str, T.Any]] = []

    async def search_work_packages(self, *, filters=None, page_size=100):  # noqa: ANN001
        self.calls.append({'filters': filters, 'page_size': page_size})
        return self.results


def _stub_screen(screen: WorkPackagePickerScreen) -> None:
    screen._render_results = lambda: None  # type: ignore[assignment]
    screen._set_hint = lambda text: None  # type: ignore[assignment]


class TestWorkPackagePickerSearch:
    async def test_search_builds_subject_and_type_filter(self) -> None:
        client = _FakeClient([_wp(7160, 'SAPV Projekt')])
        screen = WorkPackagePickerScreen(client=client, type_ids=[10, 9, 8])
        _stub_screen(screen)
        await screen._do_search('sapv')
        assert client.calls[0]['filters'] == [
            {'subject': {'operator': '~', 'values': ['sapv']}},
            {'type_id': {'operator': '=', 'values': ['10', '9', '8']}},
        ]

    async def test_search_without_type_ids_omits_type_filter(self) -> None:
        client = _FakeClient([_wp(1, 'X')])
        screen = WorkPackagePickerScreen(client=client, type_ids=[])
        _stub_screen(screen)
        await screen._do_search('x')
        assert client.calls[0]['filters'] == [
            {'subject': {'operator': '~', 'values': ['x']}},
        ]

    async def test_results_store_id_and_label(self) -> None:
        client = _FakeClient([_wp(7160, 'SAPV Projekt', type_name='Projekt')])
        screen = WorkPackagePickerScreen(client=client, type_ids=[10])
        _stub_screen(screen)
        await screen._do_search('sapv')
        assert screen._results[0][0] == 7160
        assert '#7160' in screen._results[0][1]
        assert 'SAPV Projekt' in screen._results[0][1]

    async def test_search_error_clears_results(self) -> None:
        class _Boom:
            async def search_work_packages(self, *, filters=None, page_size=100):  # noqa: ANN001
                raise RuntimeError('kaputt')

        screen = WorkPackagePickerScreen(client=_Boom(), type_ids=[10])
        _stub_screen(screen)
        screen._results = [(1, 'old')]
        await screen._do_search('sapv')
        assert screen._results == []
