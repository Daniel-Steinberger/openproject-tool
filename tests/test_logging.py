from __future__ import annotations

import logging
from pathlib import Path

import pytest

from op.config import Config, ConnectionConfig, DefaultsConfig, LoggingConfig, RemoteConfig
from op.logging_setup import default_log_path, setup_logging


@pytest.fixture(autouse=True)
def _reset_logging():  # noqa: ANN202
    """Avoid handler leakage between tests."""
    logger = logging.getLogger('op')
    previous_handlers = list(logger.handlers)
    previous_level = logger.level
    for handler in previous_handlers:
        logger.removeHandler(handler)
    yield
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    for handler in previous_handlers:
        logger.addHandler(handler)
    logger.setLevel(previous_level)


class TestDefaultLogPath:
    def test_uses_xdg_state_home_when_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path))
        assert default_log_path() == tmp_path / 'openproject-tool' / 'op.log'

    def test_falls_back_to_local_state(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv('XDG_STATE_HOME', raising=False)
        monkeypatch.setenv('HOME', str(tmp_path))
        assert default_log_path() == tmp_path / '.local' / 'state' / 'openproject-tool' / 'op.log'


class TestSetupLogging:
    def test_creates_file_handler(self, tmp_path: Path) -> None:
        log_file = tmp_path / 'op.log'
        cfg = Config(
            connection=ConnectionConfig(base_url='x'),
            defaults=DefaultsConfig(),
            remote=RemoteConfig(),
            logging=LoggingConfig(level='DEBUG', file=log_file),
        )
        setup_logging(cfg)
        logger = logging.getLogger('op.test')
        logger.info('hello from test')
        for handler in logging.getLogger('op').handlers:
            handler.flush()
        assert log_file.exists()
        content = log_file.read_text()
        assert 'hello from test' in content

    def test_respects_level(self, tmp_path: Path) -> None:
        log_file = tmp_path / 'op.log'
        cfg = Config(
            connection=ConnectionConfig(base_url='x'),
            defaults=DefaultsConfig(),
            remote=RemoteConfig(),
            logging=LoggingConfig(level='WARNING', file=log_file),
        )
        setup_logging(cfg)
        logger = logging.getLogger('op.test')
        logger.info('info-message')
        logger.warning('warn-message')
        for handler in logging.getLogger('op').handlers:
            handler.flush()
        content = log_file.read_text()
        assert 'warn-message' in content
        assert 'info-message' not in content

    def test_exception_records_traceback(self, tmp_path: Path) -> None:
        log_file = tmp_path / 'op.log'
        cfg = Config(
            connection=ConnectionConfig(base_url='x'),
            defaults=DefaultsConfig(),
            remote=RemoteConfig(),
            logging=LoggingConfig(level='DEBUG', file=log_file),
        )
        setup_logging(cfg)
        logger = logging.getLogger('op.test')
        try:
            raise ValueError('boom')
        except ValueError:
            logger.exception('while doing X')
        for handler in logging.getLogger('op').handlers:
            handler.flush()
        content = log_file.read_text()
        assert 'while doing X' in content
        assert 'Traceback' in content
        assert 'ValueError: boom' in content


class TestConfigLoggingSection:
    def test_defaults_when_section_missing(self, tmp_path: Path) -> None:
        from op.config import load_config

        path = tmp_path / 'config.toml'
        path.write_text('[connection]\nbase_url = "x"\n')
        cfg = load_config(path)
        assert cfg.logging.level == 'INFO'

    def test_reads_custom_level_and_file(self, tmp_path: Path) -> None:
        from op.config import load_config

        log_file = tmp_path / 'custom.log'
        path = tmp_path / 'config.toml'
        path.write_text(
            '[connection]\n'
            'base_url = "x"\n'
            '\n'
            '[logging]\n'
            'level = "DEBUG"\n'
            f'file = "{log_file}"\n'
        )
        cfg = load_config(path)
        assert cfg.logging.level == 'DEBUG'
        assert cfg.logging.file == log_file
