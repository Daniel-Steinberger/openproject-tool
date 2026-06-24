from __future__ import annotations

import io

import httpx
import pytest
import respx
from rich.console import Console

from op.cli import _parse_args, run
from op.commits import GIT_LOG_FORMAT
from op.config import (
    Config,
    ConnectionConfig,
    DefaultsConfig,
    GitlabConfig,
    RemoteConfig,
)

BASE_URL = 'https://op.example.com'


def _console() -> tuple[io.StringIO, Console]:
    buf = io.StringIO()
    return buf, Console(file=buf, width=120, force_terminal=False)


def _config(with_cf: bool = True) -> Config:
    return Config(
        connection=ConnectionConfig(base_url=BASE_URL),
        defaults=DefaultsConfig(),
        remote=RemoteConfig(custom_fields={44: 'Commits'} if with_cf else {}),
        gitlab=GitlabConfig(base_url='https://gitlab.dvs.ag', project='dvs/dvs'),
    )


class _FakeProc:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def _fake_git(stdout: str):  # noqa: ANN202
    def _run(cmd, capture_output, text, check):  # noqa: ANN001
        return _FakeProc(stdout)
    return _run


def _wp_json(cf_raw: str = '') -> dict:
    return {
        '_type': 'WorkPackage', 'id': 7190, 'subject': 'S', 'lockVersion': 2,
        'customField44': {'raw': cf_raw, 'html': '', 'format': 'markdown'},
        '_links': {
            'type': {'href': '/api/v3/types/1', 'title': 'Task'},
            'status': {'href': '/api/v3/statuses/1', 'title': 'Neu'},
            'project': {'href': '/api/v3/projects/10', 'title': 'P'},
        },
    }


async def test_dry_run_is_local_preview_without_cf_or_api(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    monkeypatch.setenv('OP_API_KEY', 'k')
    monkeypatch.setattr(
        'subprocess.run',
        _fake_git('FULLSHA1\x1fabc1234\x1fFix login OP#7190\x1fbody\x1e'),
    )
    wp_route = respx_mock.get(f'{BASE_URL}/api/v3/work_packages/7190')
    patch_route = respx_mock.patch(f'{BASE_URL}/api/v3/work_packages/7190')

    # No "Commits" custom field configured → dry-run must still work.
    args = _parse_args(['commits', '--dry-run'])
    buf, console = _console()
    rc = await run(args, config=_config(with_cf=False), config_path=None, console=console)
    assert rc == 0
    out = buf.getvalue()
    assert '#7190' in out and 'abc1234' in out
    assert 'gitlab.dvs.ag/dvs/dvs/-/commit/FULLSHA1' in out
    assert not patch_route.called and not wp_route.called  # no API at all


async def test_writes_custom_field(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    monkeypatch.setenv('OP_API_KEY', 'k')
    monkeypatch.setattr(
        'subprocess.run',
        _fake_git('FULLSHA1\x1fabc1234\x1fFix login OP#7190\x1fbody\x1e'),
    )
    respx_mock.get(f'{BASE_URL}/api/v3/work_packages/7190').mock(
        return_value=httpx.Response(200, json=_wp_json())
    )
    import json
    patch_route = respx_mock.patch(f'{BASE_URL}/api/v3/work_packages/7190').mock(
        return_value=httpx.Response(200, json=_wp_json('x'))
    )
    args = _parse_args(['commits'])
    buf, console = _console()
    rc = await run(args, config=_config(), config_path=None, console=console)
    assert rc == 0
    body = json.loads(patch_route.calls.last.request.content)
    assert body['lockVersion'] == 2
    assert 'gitlab.dvs.ag/dvs/dvs/-/commit/FULLSHA1' in body['customField44']['raw']


async def test_missing_cf_errors(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    monkeypatch.setenv('OP_API_KEY', 'k')
    args = _parse_args(['commits'])
    buf, console = _console()
    rc = await run(args, config=_config(with_cf=False), config_path=None, console=console)
    assert rc == 2
    assert 'Commits' in buf.getvalue()
