from __future__ import annotations

from pathlib import Path

from op.notify.cache import AnalysisCache
from op.notify.grouping import group_by_work_package
from op.notify.models import Notification

from .test_models import notification_payload


def _group(*, wp_id: int = 8202, activity_ids: tuple[int, ...] = (100, 101)):
    return group_by_work_package([
        Notification.from_api(notification_payload(notif_id=i + 1, wp_id=wp_id, activity_id=aid))
        for i, aid in enumerate(activity_ids)
    ])[0]


class TestKey:
    def test_same_group_same_key(self) -> None:
        a = AnalysisCache.key_for(_group(), model='m', prompt='p')
        b = AnalysisCache.key_for(_group(), model='m', prompt='p')
        assert a == b

    def test_new_activity_changes_key(self) -> None:
        a = AnalysisCache.key_for(_group(activity_ids=(100, 101)), model='m', prompt='p')
        b = AnalysisCache.key_for(_group(activity_ids=(100, 101, 102)), model='m', prompt='p')
        assert a != b

    def test_other_model_changes_key(self) -> None:
        a = AnalysisCache.key_for(_group(), model='m1', prompt='p')
        b = AnalysisCache.key_for(_group(), model='m2', prompt='p')
        assert a != b

    def test_changed_prompt_changes_key(self) -> None:
        a = AnalysisCache.key_for(_group(), model='m', prompt='prompt one')
        b = AnalysisCache.key_for(_group(), model='m', prompt='prompt two')
        assert a != b

    def test_other_work_package_changes_key(self) -> None:
        a = AnalysisCache.key_for(_group(wp_id=1), model='m', prompt='p')
        b = AnalysisCache.key_for(_group(wp_id=2), model='m', prompt='p')
        assert a != b


class TestStore:
    def test_round_trip(self, tmp_path: Path) -> None:
        cache = AnalysisCache(directory=tmp_path)
        cache.set('k', {'classification': 'churn'})
        assert cache.get('k') == {'classification': 'churn'}

    def test_miss_returns_none(self, tmp_path: Path) -> None:
        assert AnalysisCache(directory=tmp_path).get('nope') is None

    def test_disabled_cache_never_stores(self, tmp_path: Path) -> None:
        cache = AnalysisCache(directory=tmp_path, enabled=False)
        cache.set('k', {'classification': 'churn'})
        assert cache.get('k') is None
        assert list(tmp_path.iterdir()) == []

    def test_corrupt_entry_is_treated_as_miss(self, tmp_path: Path) -> None:
        cache = AnalysisCache(directory=tmp_path)
        cache.set('k', {'a': 1})
        broken = next(tmp_path.glob('*.json'))
        broken.write_text('{ this is not json')
        assert cache.get('k') is None

    def test_unwritable_directory_does_not_raise(self, tmp_path: Path) -> None:
        target = tmp_path / 'file-in-the-way'
        target.write_text('not a directory')
        cache = AnalysisCache(directory=target / 'sub')
        cache.set('k', {'a': 1})  # must not raise
        assert cache.get('k') is None
