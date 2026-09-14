from __future__ import annotations

import json
import typing as T
from pathlib import Path

import httpx
import pytest
import respx
from rich.console import Console

from op.config import Config, ConnectionConfig, LlmConfig, NotificationsConfig
from op.notify.cli import parse_notify_args, run_notify

from .test_models import notification_payload

OP_URL = 'https://op.example.com'
LLM_URL = 'http://llm.example.com:8000/v1'


def _config(tmp_path: Path, **llm_kwargs: T.Any) -> Config:
    return Config(
        connection=ConnectionConfig(base_url=OP_URL, api_key='key'),
        llm=LlmConfig(base_url=LLM_URL, model='test-model', **llm_kwargs),
        notifications=NotificationsConfig(cache_enabled=False),
    )


def _console() -> tuple[Console, T.Callable[[], str]]:
    console = Console(record=True, width=120, force_terminal=False)
    return console, lambda: console.export_text()


def _mock_openproject(
    respx_mock: respx.MockRouter, *, notifications: list[dict] | None = None
) -> None:
    respx_mock.get(f'{OP_URL}/api/v3/users/me').mock(
        return_value=httpx.Response(200, json={'id': 7, 'name': 'Dana Muster'})
    )
    elements = notifications if notifications is not None else [
        notification_payload(notif_id=1, wp_id=100, activity_id=500, reason='mentioned'),
        notification_payload(notif_id=2, wp_id=200, activity_id=600, reason='responsible'),
    ]
    respx_mock.get(f'{OP_URL}/api/v3/notifications').mock(
        return_value=httpx.Response(200, json={
            'total': len(elements), 'count': len(elements),
            '_embedded': {'elements': elements}, '_links': {},
        })
    )
    respx_mock.get(url__regex=rf'{OP_URL}/api/v3/work_packages/\d+$').mock(
        return_value=httpx.Response(200, json={
            'id': 100, 'subject': 'Ein Vorgang', 'lockVersion': 1,
            '_links': {
                'type': {'href': '/api/v3/types/1', 'title': 'Task'},
                'status': {'href': '/api/v3/statuses/1', 'title': 'Neu'},
                'project': {'href': '/api/v3/projects/1', 'title': 'Projekt'},
            },
        })
    )
    respx_mock.get(url__regex=rf'{OP_URL}/api/v3/work_packages/\d+/activities').mock(
        return_value=httpx.Response(200, json={
            'total': 1, 'count': 1,
            '_embedded': {'elements': [{
                'id': 500, 'createdAt': '2026-09-10T10:00:00Z',
                'comment': {'raw': 'Bitte einmal anschauen'}, 'details': [],
                '_links': {'user': {'href': '/api/v3/users/16', 'title': 'Bea'}},
            }]},
        })
    )


def _mock_llm(respx_mock: respx.MockRouter, *, classification: str = 'churn') -> respx.Route:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        is_report = 'triage_results' in body['messages'][1]['content']
        content = (
            '## Bericht\n\nAlles Wesentliche steht hier.'
            if is_report
            else json.dumps({
                'classification': classification, 'title': 'Titel', 'summary': 'Zusammenfassung',
                'open_points': [], 'waits_for_me': False, 'rationale': 'weil',
            })
        )
        return httpx.Response(200, json={
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': content}}],
        })

    return respx_mock.post(f'{LLM_URL}/chat/completions').mock(side_effect=handler)


class TestParseArgs:
    def test_defaults(self) -> None:
        args = parse_notify_args([])
        assert args.interactive is False
        assert args.no_llm is False
        assert args.refresh is False
        assert args.mark_read == []
        assert args.mark_read_churn is False
        assert args.mark_read_all is False

    def test_flags(self) -> None:
        args = parse_notify_args(['-i', '--no-llm', '--refresh', '--mark-read', '10', '20'])
        assert args.interactive is True
        assert args.no_llm is True
        assert args.refresh is True
        assert args.mark_read == [10, 20]

    def test_mark_flags(self) -> None:
        assert parse_notify_args(['--mark-read-churn']).mark_read_churn is True
        assert parse_notify_args(['--mark-read-all']).mark_read_all is True


class TestRunWithoutLlm:
    async def test_lists_groups_and_never_calls_the_model(
        self, respx_mock: respx.MockRouter, tmp_path: Path
    ) -> None:
        _mock_openproject(respx_mock)
        console, text = _console()
        code = await run_notify(
            parse_notify_args(['--no-llm']), config=_config(tmp_path), console=console
        )
        assert code == 0
        out = text()
        assert '100' in out and '200' in out
        assert 'mentioned' in out

    async def test_empty_inbox_is_stated_plainly(
        self, respx_mock: respx.MockRouter, tmp_path: Path
    ) -> None:
        _mock_openproject(respx_mock, notifications=[])
        console, text = _console()
        code = await run_notify(
            parse_notify_args([]), config=_config(tmp_path), console=console
        )
        assert code == 0
        assert 'ungelesen' in text().lower()


class TestRunWithLlm:
    async def test_prints_the_report(
        self, respx_mock: respx.MockRouter, tmp_path: Path
    ) -> None:
        _mock_openproject(respx_mock)
        _mock_llm(respx_mock)
        console, text = _console()
        code = await run_notify(parse_notify_args([]), config=_config(tmp_path), console=console)
        assert code == 0
        assert 'Alles Wesentliche steht hier' in text()

    async def test_unreachable_llm_explains_itself(
        self, respx_mock: respx.MockRouter, tmp_path: Path
    ) -> None:
        _mock_openproject(respx_mock)
        respx_mock.post(f'{LLM_URL}/chat/completions').mock(
            side_effect=httpx.ConnectError('refused')
        )
        console, text = _console()
        code = await run_notify(parse_notify_args([]), config=_config(tmp_path), console=console)
        assert code == 3
        out = text()
        assert 'llm.example.com' in out
        assert '--no-llm' in out

    async def test_missing_model_names_what_the_server_offers(
        self, respx_mock: respx.MockRouter, tmp_path: Path
    ) -> None:
        _mock_openproject(respx_mock)
        respx_mock.get(f'{LLM_URL}/models').mock(
            return_value=httpx.Response(200, json={'data': [{'id': 'a-model'}, {'id': 'b-model'}]})
        )
        config = _config(tmp_path)
        config.llm.model = ''
        console, text = _console()
        code = await run_notify(parse_notify_args([]), config=config, console=console)
        assert code == 2
        out = text()
        assert 'a-model' in out and 'b-model' in out
        assert 'model' in out


class TestMarking:
    async def test_mark_read_by_work_package(
        self, respx_mock: respx.MockRouter, tmp_path: Path
    ) -> None:
        _mock_openproject(respx_mock)
        _mock_llm(respx_mock)
        route = respx_mock.post(f'{OP_URL}/api/v3/notifications/1/read_ian').mock(
            return_value=httpx.Response(204)
        )
        console, text = _console()
        code = await run_notify(
            parse_notify_args(['--mark-read', '100']), config=_config(tmp_path), console=console
        )
        assert code == 0
        assert route.called
        assert 'gelesen' in text().lower()

    async def test_mark_read_churn_only_touches_churn(
        self, respx_mock: respx.MockRouter, tmp_path: Path
    ) -> None:
        _mock_openproject(respx_mock)
        _mock_llm(respx_mock, classification='relevant')
        marked = respx_mock.post(url__regex=rf'{OP_URL}/api/v3/notifications/\d+/read_ian').mock(
            return_value=httpx.Response(204)
        )
        console, _ = _console()
        code = await run_notify(
            parse_notify_args(['--mark-read-churn']), config=_config(tmp_path), console=console
        )
        assert code == 0
        assert not marked.called  # everything was classified relevant

    async def test_mark_read_all(self, respx_mock: respx.MockRouter, tmp_path: Path) -> None:
        _mock_openproject(respx_mock)
        _mock_llm(respx_mock)
        marked = respx_mock.post(url__regex=rf'{OP_URL}/api/v3/notifications/\d+/read_ian').mock(
            return_value=httpx.Response(204)
        )
        console, _ = _console()
        code = await run_notify(
            parse_notify_args(['--mark-read-all']), config=_config(tmp_path), console=console
        )
        assert code == 0
        assert marked.call_count == 2

    async def test_unknown_id_is_rejected(
        self, respx_mock: respx.MockRouter, tmp_path: Path
    ) -> None:
        _mock_openproject(respx_mock)
        _mock_llm(respx_mock)
        console, text = _console()
        code = await run_notify(
            parse_notify_args(['--mark-read', '9999']), config=_config(tmp_path), console=console
        )
        assert code == 2
        assert '9999' in text()

    async def test_marking_works_without_the_model(
        self, respx_mock: respx.MockRouter, tmp_path: Path
    ) -> None:
        """--no-llm --mark-read-all must not require a model to be reachable."""
        _mock_openproject(respx_mock)
        marked = respx_mock.post(url__regex=rf'{OP_URL}/api/v3/notifications/\d+/read_ian').mock(
            return_value=httpx.Response(204)
        )
        console, _ = _console()
        code = await run_notify(
            parse_notify_args(['--no-llm', '--mark-read-all']),
            config=_config(tmp_path), console=console,
        )
        assert code == 0
        assert marked.call_count == 2

    async def test_churn_marking_refuses_without_the_model(
        self, respx_mock: respx.MockRouter, tmp_path: Path
    ) -> None:
        """Without a classification there is no churn to speak of."""
        _mock_openproject(respx_mock)
        console, text = _console()
        code = await run_notify(
            parse_notify_args(['--no-llm', '--mark-read-churn']),
            config=_config(tmp_path), console=console,
        )
        assert code == 2
        assert '--no-llm' in text()


class TestApiKey:
    async def test_missing_api_key_is_reported(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv('OP_API_KEY', raising=False)
        config = _config(tmp_path)
        config.connection.api_key = None
        console, text = _console()
        code = await run_notify(parse_notify_args([]), config=config, console=console)
        assert code == 2
        assert 'API' in text()


class TestModeWiring:
    def test_op_parses_notify_as_a_mode(self) -> None:
        from op.cli import _parse_args

        args = _parse_args(['notify', '--no-llm'])
        assert args.command == 'notify'
        assert args.no_llm is True

    def test_notify_mode_is_listed_in_help(self) -> None:
        from op.cli import _modes_epilog

        assert 'notify' in _modes_epilog()

    async def test_run_dispatches_to_notify(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import op.cli as op_cli
        from op.cli import _parse_args, run

        seen: list[str] = []

        async def fake_run_notify(args, *, config, config_path, console) -> int:
            seen.append(args.command)
            return 0

        monkeypatch.setattr(op_cli, 'run_notify', fake_run_notify)
        code = await run(_parse_args(['notify']), config=_config(tmp_path), config_path=tmp_path)
        assert code == 0
        assert seen == ['notify']


class TestOverviewTable:
    def test_columns_survive_a_long_title(self) -> None:
        """A wide title must not squeeze the id and flag columns down to nothing."""
        from op.notify.analysis import GroupAnalysis
        from op.notify.cli import _overview

        analyses = [GroupAnalysis(
            work_package_id=8202,
            title='Ein sehr langer Titel ' * 10,
            classification='relevant', summary='S', waits_for_me=True,
            notification_ids=[1],
        )]
        console = Console(record=True, width=80, force_terminal=False)
        console.print(_overview(analyses))
        text = console.export_text
        out = text()
        assert '8202' in out
        assert 'relevant' in out
        assert '✓' in out
