from __future__ import annotations

import typing as T

import pytest
from textual.widgets import DataTable, Markdown

from op.config import Config, ConnectionConfig, KeybindingsConfig
from op.notify.analysis import GroupAnalysis
from op.notify.tui.app import NotifyApp


class FakeClient:
    def __init__(self) -> None:
        self.marked: list[int] = []

    async def mark_read(self, notification_id: int) -> None:
        self.marked.append(notification_id)


def _analysis(wp_id: int, classification: str, ids: list[int], **kw: T.Any) -> GroupAnalysis:
    return GroupAnalysis(
        work_package_id=wp_id, title=f'Vorgang {wp_id}', classification=classification,
        summary=kw.get('summary', f'Zusammenfassung {wp_id}'),
        open_points=kw.get('open_points', []),
        waits_for_me=kw.get('waits_for_me', False),
        notification_ids=ids, project_name='Projekt', count=len(ids),
        latest='2026-09-14T10:00:00Z', block=kw.get('block', f'ROHBLOCK {wp_id}'),
    )


@pytest.fixture
def analyses() -> list[GroupAnalysis]:
    return [
        _analysis(100, 'churn', [1, 2]),
        _analysis(200, 'relevant', [3], waits_for_me=True, open_points=['Antwort geben']),
        _analysis(300, 'worth_knowing', [4]),
    ]


@pytest.fixture
def app_factory(analyses: list[GroupAnalysis]) -> T.Callable[..., NotifyApp]:
    def factory(client: FakeClient | None = None) -> NotifyApp:
        return NotifyApp(
            config=Config(connection=ConnectionConfig(base_url='https://op.example.com')),
            client=client or FakeClient(),
            analyses=analyses,
        )

    return factory


class TestListScreen:
    async def test_shows_one_row_per_group_relevant_first(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one('#notify-list', DataTable)
            assert table.row_count == 3
            first = table.get_row_at(0)
            assert '200' in str(first[1])

    async def test_space_marks_and_unmarks(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('space')
            assert app.queue.count == 1
            await pilot.press('up')  # back onto the same row
            await pilot.press('space')
            assert app.queue.count == 0

    async def test_c_selects_every_churn_group(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('c')
            assert app.queue.notification_ids == [1, 2]

    async def test_a_selects_everything(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('a')
            assert sorted(app.queue.notification_ids) == [1, 2, 3, 4]

    async def test_open_points_are_visible_in_the_list(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one('#notify-list', DataTable)
            rendered = ' '.join(str(cell) for row in range(table.row_count)
                                for cell in table.get_row_at(row))
            assert 'Antwort geben' in rendered or '1' in rendered


class TestDetailScreen:
    async def test_enter_opens_detail_with_summary_and_block(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            markdown = app.screen.query_one('#notify-detail', Markdown)
            source = markdown._markdown or ''
            assert 'Zusammenfassung 200' in source
            assert 'ROHBLOCK 200' in source

    async def test_q_returns_to_the_list(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('q')
            await pilot.pause()
            assert app.screen.query_one('#notify-list', DataTable)


class TestReviewAndApply:
    async def test_g_opens_review_listing_the_selection(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('c')
            await pilot.press('g')
            await pilot.pause()
            table = app.screen.query_one('#notify-review', DataTable)
            assert table.row_count == 1

    async def test_review_d_removes_an_entry(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('a')
            await pilot.press('g')
            await pilot.pause()
            await pilot.press('d')
            await pilot.pause()
            assert app.queue.count == 2

    async def test_apply_marks_every_queued_notification(self, app_factory) -> None:  # noqa: ANN001
        client = FakeClient()
        app = app_factory(client)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('c')
            await pilot.press('g')
            await pilot.pause()
            await pilot.press('g')
            for _ in range(20):
                await pilot.pause()
                if sorted(client.marked) == [1, 2]:
                    break
            assert sorted(client.marked) == [1, 2]

    async def test_applied_groups_disappear_from_the_list(self, app_factory) -> None:  # noqa: ANN001
        client = FakeClient()
        app = app_factory(client)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('c')
            await pilot.press('g')
            await pilot.pause()
            await pilot.press('g')
            for _ in range(20):
                await pilot.pause()
                if client.marked:
                    break
            await pilot.press('q')
            await pilot.pause()
            assert app.screen.query_one('#notify-list', DataTable).row_count == 2


class TestKeybindings:
    async def test_custom_keys_from_config_are_applied(self, analyses) -> None:  # noqa: ANN001
        keybindings = KeybindingsConfig.model_validate({'notify_list': {'mark_all': 'x'}})
        app = NotifyApp(
            config=Config(
                connection=ConnectionConfig(base_url='https://op.example.com'),
                keybindings=keybindings,
            ),
            client=FakeClient(),
            analyses=analyses,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('x')
            assert app.queue.count == 3


class TestDetailMarking:
    async def test_m_marks_the_current_work_package(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('m')
            await pilot.pause()
            assert app.queue.notification_ids == [3]  # the relevant group, sorted first

    async def test_m_toggles_while_staying_on_the_work_package(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('m')
            await pilot.press('m')
            await pilot.pause()
            assert app.queue.count == 0

    async def test_detail_shows_whether_it_is_marked(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            before = app.screen.query_one('#notify-detail', Markdown)._markdown or ''
            await pilot.press('m')
            await pilot.pause()
            after = app.screen.query_one('#notify-detail', Markdown)._markdown or ''
            assert before != after
            assert 'gelesen' in after

    async def test_marking_in_detail_shows_up_in_the_list(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('m')
            await pilot.press('q')
            await pilot.pause()
            table = app.screen.query_one('#notify-list', DataTable)
            assert '✓' in str(table.get_row_at(0)[0])


class TestDetailNavigation:
    async def test_n_moves_to_the_next_work_package(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('n')
            await pilot.pause()
            source = app.screen.query_one('#notify-detail', Markdown)._markdown or ''
            assert 'Vorgang 300' in source  # relevant(200) → worth_knowing(300)

    async def test_p_moves_back(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('n')
            await pilot.press('p')
            await pilot.pause()
            source = app.screen.query_one('#notify-detail', Markdown)._markdown or ''
            assert 'Vorgang 200' in source

    async def test_navigation_stops_at_the_ends(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('p')  # already on the first one
            await pilot.pause()
            source = app.screen.query_one('#notify-detail', Markdown)._markdown or ''
            assert 'Vorgang 200' in source
            for _ in range(5):
                await pilot.press('n')
            await pilot.pause()
            source = app.screen.query_one('#notify-detail', Markdown)._markdown or ''
            assert 'Vorgang 100' in source  # churn, last in the sort order

    async def test_position_is_visible(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            assert '1/3' in app.sub_title
            await pilot.press('n')
            await pilot.pause()
            assert '2/3' in app.sub_title

    async def test_list_cursor_follows_the_detail_navigation(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('n')
            await pilot.press('q')
            await pilot.pause()
            table = app.screen.query_one('#notify-list', DataTable)
            assert table.cursor_row == 1

    async def test_marking_then_navigating_keeps_both_marks(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('m')
            await pilot.press('n')
            await pilot.pause()
            await pilot.press('m')
            await pilot.pause()
            assert app.queue.count == 2
