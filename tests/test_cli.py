from __future__ import annotations

import io
import typing as T

import httpx
import pytest
import respx
from rich.console import Console

from op.cli import (
    _parse_args,
    format_result_line,
    format_task_detail,
    run,
)
from op.config import Config, ConnectionConfig, DefaultsConfig, RemoteConfig
from op.models import WorkPackage

BASE_URL = 'https://op.example.com'


def _wp(**overrides: T.Any) -> WorkPackage:
    defaults: dict[str, T.Any] = {
        'id': 1,
        'subject': 'Subject',
        'description': None,
        'type_id': 1,
        'type_name': 'Task',
        'status_id': 1,
        'status_name': 'Neu',
        'project_id': 10,
        'project_name': 'Web',
        'lock_version': 1,
    }
    defaults.update(overrides)
    return WorkPackage(**defaults)


class TestParseArgs:
    def test_load_remote_data_flag(self) -> None:
        args = _parse_args(['--load-remote-data'])
        assert args.load_remote_data is True
        assert args.interactive is False
        assert args.query == []

    def test_search_positional(self) -> None:
        args = _parse_args(['word1', 'word2', 'type=bug'])
        assert args.load_remote_data is False
        assert args.query == ['word1', 'word2', 'type=bug']

    def test_interactive(self) -> None:
        args = _parse_args(['-i', '1234'])
        assert args.interactive is True
        assert args.query == ['1234']

    def test_interactive_long(self) -> None:
        args = _parse_args(['--interactive'])
        assert args.interactive is True


class TestFormatResultLine:
    def test_contains_id_subject_and_url(self) -> None:
        wp = _wp(id=1234, subject='Hallo Welt')
        rendered = _render(format_result_line(wp, BASE_URL))
        assert 'OP#1234' in rendered
        assert 'Hallo Welt' in rendered
        assert f'{BASE_URL}/work_packages/1234' in rendered

    def test_long_subject_not_truncated(self) -> None:
        subject = 'Ein sehr langer Titel mit vielen Wörtern die trotzdem vollständig angezeigt werden'
        wp = _wp(id=1, subject=subject)
        rendered = _render(format_result_line(wp, BASE_URL), width=200)
        assert subject in rendered


class TestFormatTaskDetail:
    def test_shows_meta_and_subject(self) -> None:
        wp = _wp(
            id=42,
            subject='Deploy Pipeline',
            status_name='In Bearbeitung',
            type_name='Bug',
            project_name='Web',
        )
        rendered = _render(format_task_detail(wp, BASE_URL), width=120)
        assert 'OP#42' in rendered
        assert 'Deploy Pipeline' in rendered
        assert 'In Bearbeitung' in rendered
        assert 'Bug' in rendered
        assert 'Web' in rendered

    def test_shows_description_when_present(self) -> None:
        wp = _wp(subject='S', description='Beschreibungstext hier')
        rendered = _render(format_task_detail(wp, BASE_URL), width=120)
        assert 'Beschreibungstext hier' in rendered

    def test_shows_assignee_when_present(self) -> None:
        wp = _wp(subject='S', assignee_id=5, assignee_name='Max Mustermann')
        rendered = _render(format_task_detail(wp, BASE_URL), width=120)
        assert 'Max Mustermann' in rendered

    def test_omits_assignee_when_absent(self) -> None:
        wp = _wp(subject='S')
        rendered = _render(format_task_detail(wp, BASE_URL), width=120)
        assert 'Assignee' not in rendered and 'Zugewiesen' not in rendered


class TestRunEndToEnd:
    async def test_search_by_id_prints_task(
        self, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
    ) -> None:
        monkeypatch.setenv('OP_API_KEY', 'test')
        config = Config(
            connection=ConnectionConfig(base_url=BASE_URL),
            defaults=DefaultsConfig(),
            remote=RemoteConfig(),
        )
        respx_mock.get(f'{BASE_URL}/api/v3/work_packages/1234').mock(
            return_value=httpx.Response(
                200,
                json={
                    '_type': 'WorkPackage',
                    'id': 1234,
                    'subject': 'Direkt geladen',
                    'description': {'raw': 'Body'},
                    'lockVersion': 1,
                    '_links': {
                        'type': {'href': '/api/v3/types/1', 'title': 'Task'},
                        'status': {'href': '/api/v3/statuses/1', 'title': 'Neu'},
                        'project': {'href': '/api/v3/projects/10', 'title': 'Web'},
                    },
                },
            )
        )
        args = _parse_args(['1234'])
        buf, console = _buffered_console()
        await run(args, config=config, config_path=None, console=console)
        assert 'OP#1234' in buf.getvalue()
        assert 'Direkt geladen' in buf.getvalue()

    async def test_interactive_mode_passes_client_to_opapp(
        self, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
    ) -> None:
        """Regression: cli.run must forward the OpenProjectClient into OpApp(client=...)."""
        import httpx

        from op.api import OpenProjectClient
        from op.tui.app import OpApp

        monkeypatch.setenv('OP_API_KEY', 'test')
        config = Config(
            connection=ConnectionConfig(base_url=BASE_URL),
            defaults=DefaultsConfig(),
            remote=RemoteConfig(),
        )
        # Give the empty-filter interactive branch at least one task so we hit the TUI path.
        respx_mock.get(f'{BASE_URL}/api/v3/work_packages').mock(
            return_value=httpx.Response(
                200,
                json={'total': 0, 'count': 0, '_embedded': {'elements': []}},
            )
        )

        captured: dict = {}

        original_init = OpApp.__init__

        def _spy_init(self, *, tasks, config, client=None, config_path=None, query=None):  # noqa: ANN001, ANN202
            captured['client'] = client
            original_init(
                self, tasks=tasks, config=config, client=client,
                config_path=config_path, query=query,
            )
            raise SystemExit(0)

        monkeypatch.setattr(OpApp, '__init__', _spy_init)

        args = _parse_args(['-i', 'nothing'])
        try:
            await run(args, config=config, config_path=None, console=Console())
        except SystemExit:
            pass

        assert captured.get('client') is not None
        assert isinstance(captured['client'], OpenProjectClient)

    async def test_search_by_words_prints_list(
        self, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
    ) -> None:
        monkeypatch.setenv('OP_API_KEY', 'test')
        config = Config(
            connection=ConnectionConfig(base_url=BASE_URL),
            defaults=DefaultsConfig(),
            remote=RemoteConfig(),
        )
        respx_mock.get(f'{BASE_URL}/api/v3/work_packages').mock(
            return_value=httpx.Response(
                200,
                json={
                    'total': 2,
                    'count': 2,
                    '_embedded': {
                        'elements': [
                            {
                                '_type': 'WorkPackage',
                                'id': 1,
                                'subject': 'Erstes Ergebnis',
                                'description': {'raw': ''},
                                'lockVersion': 1,
                                '_links': {
                                    'type': {'href': '/api/v3/types/1', 'title': 'Task'},
                                    'status': {'href': '/api/v3/statuses/1', 'title': 'Neu'},
                                    'project': {'href': '/api/v3/projects/10', 'title': 'Web'},
                                },
                            },
                            {
                                '_type': 'WorkPackage',
                                'id': 2,
                                'subject': 'Zweites Ergebnis',
                                'description': {'raw': ''},
                                'lockVersion': 1,
                                '_links': {
                                    'type': {'href': '/api/v3/types/1', 'title': 'Task'},
                                    'status': {'href': '/api/v3/statuses/1', 'title': 'Neu'},
                                    'project': {'href': '/api/v3/projects/10', 'title': 'Web'},
                                },
                            },
                        ]
                    },
                },
            )
        )
        args = _parse_args(['Ergebnis'])
        buf, console = _buffered_console()
        await run(args, config=config, config_path=None, console=console)
        out = buf.getvalue()
        assert 'OP#1' in out and 'OP#2' in out

    async def test_unknown_filter_key_yields_friendly_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('OP_API_KEY', 'test')
        config = Config(
            connection=ConnectionConfig(base_url=BASE_URL),
            defaults=DefaultsConfig(),
            remote=RemoteConfig(),
        )
        args = _parse_args(['typ=bug'])
        buf, console = _buffered_console()
        exit_code = await run(args, config=config, config_path=None, console=console)
        assert exit_code == 2
        out = buf.getvalue()
        assert 'typ' in out
        assert 'type' in out  # hint listing valid keys
        assert 'Traceback' not in out


def _render(renderable: T.Any, width: int = 120) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=width, force_terminal=True, color_system='truecolor')
    console.print(renderable)
    return buffer.getvalue()


def _buffered_console(width: int = 120) -> tuple[io.StringIO, Console]:
    buffer = io.StringIO()
    console = Console(file=buffer, width=width, force_terminal=True, color_system='truecolor')
    return buffer, console
