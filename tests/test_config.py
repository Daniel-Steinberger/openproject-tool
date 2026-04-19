from __future__ import annotations

from pathlib import Path

import pytest

from op.config import (
    Config,
    ConnectionConfig,
    default_config_path,
    get_api_key,
    load_config,
    update_remote,
)


class TestDefaultConfigPath:
    def test_uses_xdg_config_home_when_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
        assert default_config_path() == tmp_path / 'openproject-tool' / 'config.toml'

    def test_falls_back_to_home_config_when_xdg_unset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
        monkeypatch.setenv('HOME', str(tmp_path))
        assert default_config_path() == tmp_path / '.config' / 'openproject-tool' / 'config.toml'


class TestLoadConfig:
    def test_creates_default_when_missing(self, tmp_path: Path) -> None:
        path = tmp_path / 'config.toml'
        cfg = load_config(path)
        assert path.exists()
        assert cfg.connection.base_url  # placeholder
        assert cfg.connection.api_key is None

    def test_default_config_has_comments(self, tmp_path: Path) -> None:
        path = tmp_path / 'config.toml'
        load_config(path)
        content = path.read_text()
        assert '# API key' in content or '# api_key' in content.lower()
        assert 'OP_API_KEY' in content

    def test_reads_existing(self, tmp_path: Path) -> None:
        path = tmp_path / 'config.toml'
        path.write_text(
            '[connection]\n'
            'base_url = "https://example.com"\n'
            'api_key = "secret"\n'
            '\n'
            '[defaults]\n'
            'status = ["open"]\n'
            'type = ["Task", "Bug"]\n'
        )
        cfg = load_config(path)
        assert cfg.connection.base_url == 'https://example.com'
        assert cfg.connection.api_key == 'secret'
        assert cfg.defaults.status == ['open']
        assert cfg.defaults.type == ['Task', 'Bug']

    def test_reads_empty_remote_sections(self, tmp_path: Path) -> None:
        path = tmp_path / 'config.toml'
        path.write_text('[connection]\nbase_url = "https://x.com"\n')
        cfg = load_config(path)
        assert cfg.remote.statuses == {}
        assert cfg.remote.types == {}
        assert cfg.remote.users == {}

    def test_reads_remote_with_numeric_keys(self, tmp_path: Path) -> None:
        path = tmp_path / 'config.toml'
        path.write_text(
            '[connection]\n'
            'base_url = "https://x.com"\n'
            '\n'
            '[remote.statuses]\n'
            '1 = "Neu"\n'
            '2 = "In Bearbeitung"\n'
        )
        cfg = load_config(path)
        assert cfg.remote.statuses == {1: 'Neu', 2: 'In Bearbeitung'}


class TestFilterConfig:
    def test_default_filter_config(self, tmp_path: Path) -> None:
        path = tmp_path / 'config.toml'
        path.write_text('[connection]\nbase_url = "x"\n')
        cfg = load_config(path)
        assert cfg.filter.irrelevant_projects == []
        assert cfg.filter.project_filter_active is False

    def test_reads_filter_section(self, tmp_path: Path) -> None:
        path = tmp_path / 'config.toml'
        path.write_text(
            '[connection]\nbase_url = "x"\n\n'
            '[filter]\n'
            'irrelevant_projects = [10, 11, 12]\n'
            'project_filter_active = true\n'
        )
        cfg = load_config(path)
        assert cfg.filter.irrelevant_projects == [10, 11, 12]
        assert cfg.filter.project_filter_active is True


class TestUpdateFilter:
    def test_save_filter_state(self, tmp_path: Path) -> None:
        from op.config import update_filter

        path = tmp_path / 'config.toml'
        load_config(path)
        update_filter(path, irrelevant_projects=[5, 7], project_filter_active=True)
        cfg = load_config(path)
        assert cfg.filter.irrelevant_projects == [5, 7]
        assert cfg.filter.project_filter_active is True

    def test_save_filter_preserves_other_sections(self, tmp_path: Path) -> None:
        from op.config import update_filter

        path = tmp_path / 'config.toml'
        path.write_text(
            '[connection]\nbase_url = "keep"\napi_key = "secret"\n\n'
            '[defaults]\nstatus = ["open"]\n'
        )
        update_filter(path, irrelevant_projects=[1], project_filter_active=False)
        cfg = load_config(path)
        assert cfg.connection.base_url == 'keep'
        assert cfg.connection.api_key == 'secret'
        assert cfg.defaults.status == ['open']
        assert cfg.filter.irrelevant_projects == [1]


class TestProjectParents:
    def test_default_empty(self, tmp_path: Path) -> None:
        path = tmp_path / 'config.toml'
        path.write_text('[connection]\nbase_url = "x"\n')
        cfg = load_config(path)
        assert cfg.remote.project_parents == {}

    def test_reads_parent_mapping(self, tmp_path: Path) -> None:
        path = tmp_path / 'config.toml'
        path.write_text(
            '[connection]\nbase_url = "x"\n\n'
            '[remote.project_parents]\n'
            '10 = 3\n'
            '11 = 3\n'
        )
        cfg = load_config(path)
        assert cfg.remote.project_parents == {10: 3, 11: 3}


class TestGetApiKey:
    def test_env_var_wins_over_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('OP_API_KEY', 'env-key')
        cfg = Config(connection=ConnectionConfig(base_url='https://x', api_key='config-key'))
        assert get_api_key(cfg) == 'env-key'

    def test_falls_back_to_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv('OP_API_KEY', raising=False)
        cfg = Config(connection=ConnectionConfig(base_url='https://x', api_key='config-key'))
        assert get_api_key(cfg) == 'config-key'

    def test_none_when_neither_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv('OP_API_KEY', raising=False)
        cfg = Config(connection=ConnectionConfig(base_url='https://x'))
        assert get_api_key(cfg) is None

    def test_ignores_empty_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('OP_API_KEY', '')
        cfg = Config(connection=ConnectionConfig(base_url='https://x', api_key='config-key'))
        assert get_api_key(cfg) == 'config-key'


class TestUpdateRemote:
    def test_writes_remote_sections(self, tmp_path: Path) -> None:
        path = tmp_path / 'config.toml'
        load_config(path)
        update_remote(
            path,
            statuses={1: 'Neu', 2: 'Offen'},
            types={1: 'Task', 2: 'Bug'},
            users={5: 'Max Mustermann'},
            projects={10: 'Webportal'},
            custom_fields={3: 'Story Points'},
        )
        cfg = load_config(path)
        assert cfg.remote.statuses == {1: 'Neu', 2: 'Offen'}
        assert cfg.remote.types == {1: 'Task', 2: 'Bug'}
        assert cfg.remote.users == {5: 'Max Mustermann'}
        assert cfg.remote.projects == {10: 'Webportal'}
        assert cfg.remote.custom_fields == {3: 'Story Points'}

    def test_preserves_connection_and_defaults(self, tmp_path: Path) -> None:
        path = tmp_path / 'config.toml'
        path.write_text(
            '[connection]\n'
            'base_url = "https://example.com"\n'
            'api_key = "secret"\n'
            '\n'
            '[defaults]\n'
            'status = ["open"]\n'
            'type = ["Task"]\n'
        )
        update_remote(path, statuses={1: 'Neu'})
        cfg = load_config(path)
        assert cfg.connection.base_url == 'https://example.com'
        assert cfg.connection.api_key == 'secret'
        assert cfg.defaults.status == ['open']
        assert cfg.defaults.type == ['Task']
        assert cfg.remote.statuses == {1: 'Neu'}

    def test_preserves_user_comments(self, tmp_path: Path) -> None:
        path = tmp_path / 'config.toml'
        path.write_text(
            '# My personal comment\n'
            '[connection]\n'
            'base_url = "https://x.com"\n'
            '# inline comment for api_key\n'
            'api_key = "secret"\n'
        )
        update_remote(path, statuses={1: 'Neu'})
        content = path.read_text()
        assert '# My personal comment' in content
        assert '# inline comment for api_key' in content

    def test_replaces_stale_remote_sections(self, tmp_path: Path) -> None:
        path = tmp_path / 'config.toml'
        load_config(path)
        update_remote(path, statuses={1: 'Neu', 2: 'Alt'})
        update_remote(path, statuses={1: 'Neu'})  # only one now
        cfg = load_config(path)
        assert cfg.remote.statuses == {1: 'Neu'}

    def test_partial_update_keeps_other_sections(self, tmp_path: Path) -> None:
        path = tmp_path / 'config.toml'
        load_config(path)
        update_remote(path, statuses={1: 'Neu'}, types={1: 'Task'})
        update_remote(path, statuses={2: 'Offen'})  # only statuses given
        cfg = load_config(path)
        assert cfg.remote.statuses == {2: 'Offen'}
        assert cfg.remote.types == {1: 'Task'}  # preserved
