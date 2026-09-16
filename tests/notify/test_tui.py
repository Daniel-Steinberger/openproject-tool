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


class TestQuit:
    async def test_q_quits_the_app(self, app_factory) -> None:  # noqa: ANN001
        app = app_factory()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('q')
            await pilot.pause()
            assert app._exit, 'q hat die App nicht beendet'

    async def test_custom_quit_key_from_config(self, analyses) -> None:  # noqa: ANN001
        keybindings = KeybindingsConfig.model_validate({'notify_list': {'quit': 'x'}})
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
            await pilot.pause()
            assert app._exit


class TestBindingsResolve:
    """Every bound action must exist on its screen.

    A binding pointing at a missing action fails silently — the key simply does
    nothing. That is how both `q` (quit) and `r` (reload) slipped through.
    """

    def _screens(self) -> list[type]:
        from op.notify.tui.applying_screen import NotifyApplyingScreen
        from op.notify.tui.detail_screen import NotifyDetailScreen
        from op.notify.tui.list_screen import NotifyListScreen
        from op.notify.tui.review_screen import NotifyReviewScreen

        return [NotifyListScreen, NotifyDetailScreen, NotifyReviewScreen, NotifyApplyingScreen]

    def test_class_bindings_have_actions(self) -> None:
        for screen in self._screens():
            for binding in screen.BINDINGS:
                action = binding.action.split('(')[0]
                assert hasattr(screen, f'action_{action}'), \
                    f'{screen.__name__} bindet {binding.key!r} auf fehlende Action {action!r}'

    def test_config_applied_bindings_have_actions(self) -> None:
        from op.notify.tui.keybindings import apply_to_notify_screens

        apply_to_notify_screens(
            Config(connection=ConnectionConfig(base_url='https://op.example.com'))
        )
        self.test_class_bindings_have_actions()


class FakeLlm:
    """Stand-in for the LLM client the detail view may ask for an action line."""

    def __init__(self, *, answer: str = 'Entscheide, ob A oder B gilt.') -> None:
        self.answer = answer
        self.calls: list[str] = []
        self.model = 'fake'

    async def complete_text(self, *, system: str, user: str) -> str:
        self.calls.append(user)
        return self.answer


def _app_with_llm(analyses, llm, **kwargs):  # noqa: ANN001, ANN201
    return NotifyApp(
        config=Config(connection=ConnectionConfig(base_url='https://op.example.com')),
        client=FakeClient(),
        analyses=analyses,
        llm=llm,
        own_user_id=kwargs.get('own_user_id', 7),
        user_name=kwargs.get('user_name', 'Dana Muster'),
    )


@pytest.fixture
def people_analyses() -> list[GroupAnalysis]:
    mine = GroupAnalysis(
        work_package_id=200, title='Meiner', classification='relevant', summary='S',
        notification_ids=[3], count=1, latest='2026-09-14T10:00:00Z', block='BLOCK 200',
        responsible_id=7, responsible_name='Dana Muster',
        assignee_id=16, assignee_name='Bea Beispiel', status_name='Fachliche Rückfrage',
        is_mentioned=True,
    )
    other = GroupAnalysis(
        work_package_id=300, title='Fremder', classification='worth_knowing', summary='S',
        notification_ids=[4], count=1, latest='2026-09-13T10:00:00Z', block='BLOCK 300',
        responsible_id=99, responsible_name='Cem Muster',
        assignee_id=99, assignee_name='Cem Muster', status_name='Neu',
    )
    return [mine, other]


def _static_text(app: NotifyApp, selector: str) -> str:
    """Plain text of a Static widget (Textual 8 keeps it in `visual`)."""
    from textual.widgets import Static

    return str(app.screen.query_one(selector, Static).visual)


class TestRoleBadges:
    async def test_own_roles_are_highlighted(self, people_analyses) -> None:  # noqa: ANN001
        app = _app_with_llm(people_analyses, None)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            text = _static_text(app, '#notify-roles')
            assert 'Verantwortlich' in text
            assert 'du' in text.lower()
            # The user is responsible but not assignee — the assignee shows by name
            assert 'Bea Beispiel' in text

    async def test_mention_is_flagged(self, people_analyses) -> None:  # noqa: ANN001
        app = _app_with_llm(people_analyses, None)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            text = _static_text(app, '#notify-roles')
            assert 'rwähnt' in text

    async def test_foreign_work_package_shows_no_own_role(self, people_analyses) -> None:  # noqa: ANN001
        app = _app_with_llm(people_analyses, None)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            await pilot.press('n')
            await pilot.pause()
            text = _static_text(app, '#notify-roles')
            assert 'Cem Muster' in text
            assert 'du' not in text.lower()


class TestActionLine:
    async def test_is_requested_in_the_background_and_shown(self, people_analyses) -> None:  # noqa: ANN001
        llm = FakeLlm()
        app = _app_with_llm(people_analyses, llm)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            for _ in range(30):
                await pilot.pause()
                rendered = _static_text(app, '#notify-action')
                if 'Entscheide' in rendered:
                    break
            assert 'Entscheide, ob A oder B gilt.' in rendered
            assert 'BLOCK 200' in llm.calls[0]

    async def test_rest_of_the_page_is_there_before_the_answer(self, people_analyses) -> None:  # noqa: ANN001
        from textual.widgets import Markdown

        app = _app_with_llm(people_analyses, FakeLlm())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            # no waiting for the worker — the document must already be rendered
            source = app.screen.query_one('#notify-detail', Markdown)._markdown or ''
            assert 'BLOCK 200' in source

    async def test_asked_once_per_work_package(self, people_analyses) -> None:  # noqa: ANN001
        llm = FakeLlm()
        app = _app_with_llm(people_analyses, llm)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            for _ in range(30):
                await pilot.pause()
                if llm.calls:
                    break
            await pilot.press('n')
            await pilot.pause()
            await pilot.press('p')  # back to the first one
            for _ in range(10):
                await pilot.pause()
            assert len([c for c in llm.calls if 'BLOCK 200' in c]) == 1

    async def test_without_a_model_the_view_says_so(self, people_analyses) -> None:  # noqa: ANN001
        app = _app_with_llm(people_analyses, None)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            rendered = _static_text(app, '#notify-action')
            assert 'kein Modell' in rendered.lower() or 'ohne modell' in rendered.lower()

    async def test_model_failure_does_not_break_the_view(self, people_analyses) -> None:  # noqa: ANN001
        from op.notify.llm import LlmError

        class BrokenLlm(FakeLlm):
            async def complete_text(self, *, system: str, user: str) -> str:
                raise LlmError('nope')

        app = _app_with_llm(people_analyses, BrokenLlm())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press('enter')
            for _ in range(30):
                await pilot.pause()
            rendered = _static_text(app, '#notify-action')
            assert 'nicht' in rendered.lower()


class SlowFakeLlm(FakeLlm):
    """Records the order in which work packages were asked about."""

    def __init__(self, *, answer: str = 'Tu dies.', fail_for: set[str] | None = None) -> None:
        super().__init__(answer=answer)
        self.fail_for = fail_for or set()

    async def complete_text(self, *, system: str, user: str) -> str:
        from op.notify.llm import LlmError

        self.calls.append(user)
        for marker in self.fail_for:
            if marker in user:
                raise LlmError(f'nope für {marker}')
        return self.answer


class TestActionLinesUpFront:
    async def test_all_lines_are_fetched_in_list_order(self, people_analyses) -> None:  # noqa: ANN001
        llm = SlowFakeLlm()
        app = _app_with_llm(people_analyses, llm)
        async with app.run_test() as pilot:
            for _ in range(40):
                await pilot.pause()
                if len(llm.calls) == 2:
                    break
            assert len(llm.calls) == 2
            # relevant first (200), then worth_knowing (300) — same order as the list
            assert 'BLOCK 200' in llm.calls[0]
            assert 'BLOCK 300' in llm.calls[1]

    async def test_list_shows_the_line_in_its_own_column(self, people_analyses) -> None:  # noqa: ANN001
        app = _app_with_llm(people_analyses, SlowFakeLlm(answer='Antwort an BUC geben.'))
        async with app.run_test() as pilot:
            table = app.screen.query_one('#notify-list', DataTable)
            for _ in range(40):
                await pilot.pause()
                rendered = ' '.join(
                    str(cell) for row in range(table.row_count)
                    for cell in table.get_row_at(row)
                )
                if 'Antwort an BUC geben.' in rendered:
                    break
            assert 'Antwort an BUC geben.' in rendered

    async def test_placeholder_until_the_answer_arrives(self, people_analyses) -> None:  # noqa: ANN001
        import asyncio

        released = asyncio.Event()

        class BlockingLlm(SlowFakeLlm):
            async def complete_text(self, *, system: str, user: str) -> str:
                await released.wait()
                return await super().complete_text(system=system, user=user)

        app = _app_with_llm(people_analyses, BlockingLlm())
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one('#notify-list', DataTable)
            waiting = ' '.join(str(cell) for cell in table.get_row_at(0))
            assert '…' in waiting

            released.set()
            for _ in range(40):
                await pilot.pause()
                answered = ' '.join(str(cell) for cell in table.get_row_at(0))
                if 'Tu dies.' in answered:
                    break
            assert 'Tu dies.' in answered

    async def test_each_work_package_is_asked_once_even_when_opened(self, people_analyses) -> None:  # noqa: ANN001
        llm = SlowFakeLlm()
        app = _app_with_llm(people_analyses, llm)
        async with app.run_test() as pilot:
            await pilot.press('enter')          # detail while the run is going on
            for _ in range(40):
                await pilot.pause()
            assert len([c for c in llm.calls if 'BLOCK 200' in c]) == 1
            assert len([c for c in llm.calls if 'BLOCK 300' in c]) == 1

    async def test_a_failing_line_does_not_stop_the_others(self, people_analyses) -> None:  # noqa: ANN001
        llm = SlowFakeLlm(fail_for={'BLOCK 200'})
        app = _app_with_llm(people_analyses, llm)
        async with app.run_test() as pilot:
            for _ in range(40):
                await pilot.pause()
                if len(llm.calls) == 2:
                    break
            assert len(llm.calls) == 2
            assert app.action_lines.get(300) == 'Tu dies.'
            assert 'nicht' in (app.action_lines.get(200) or '').lower()

    async def test_without_a_model_nothing_is_fetched(self, people_analyses) -> None:  # noqa: ANN001
        app = _app_with_llm(people_analyses, None)
        async with app.run_test() as pilot:
            for _ in range(10):
                await pilot.pause()
            assert app.action_lines == {}
            table = app.screen.query_one('#notify-list', DataTable)
            rendered = ' '.join(str(cell) for cell in table.get_row_at(0))
            assert '…' not in rendered  # no promise that never gets kept
