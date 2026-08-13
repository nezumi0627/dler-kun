import json
import time
from pathlib import Path

from dler_kun.managers import (
    ConfigManager,
    DownloadCacheManager,
    ResolveCacheManager,
)
from dler_kun.models import CacheStatus


def test_resolve_cache_get_set(tmp_path: Path) -> None:
    cache = ResolveCacheManager(path=tmp_path / "resolve.json", ttl_seconds=3600)
    assert cache.get("v1") is None
    cache.set("v1", "https://cdn/v1.mp4")
    assert cache.get("v1") == "https://cdn/v1.mp4"
    # persisted to disk
    reloaded = ResolveCacheManager(
        path=tmp_path / "resolve.json", ttl_seconds=3600
    )
    assert reloaded.get("v1") == "https://cdn/v1.mp4"


def test_resolve_cache_expiry(tmp_path: Path) -> None:
    cache = ResolveCacheManager(path=tmp_path / "resolve.json", ttl_seconds=-1)
    cache.set("v1", "https://cdn/v1.mp4")
    assert cache.get("v1") is None


def test_config_manager_defaults(tmp_path: Path) -> None:
    config = ConfigManager(tmp_path / "config.json")
    assert config.get("output_dir") == "downloads"
    assert config.get("85xo")["days"] == 10
    assert config.get("85xo")["max_pages"] == 50


def test_config_manager_merges_and_normalizes(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        '{"85xo": {"default_seed": "https://www.85xo.com/ja/latest-updates/", "days": 3}}',
        encoding="utf-8",
    )
    config = ConfigManager(path)
    assert config.get("85xo")["days"] == 3
    assert config.get("85xo")["default_seeds"] == [
        "https://www.85xo.com/ja/latest-updates/"
    ]
    assert "default_seed" not in config.get("85xo")


def test_download_cache_complete_check(tmp_path: Path) -> None:
    cache = DownloadCacheManager(tmp_path / "dl.json")
    target = tmp_path / "video.mp4"
    target.write_bytes(b"data" * 10)
    cache.mark("key", "https://x/v.mp4", target, CacheStatus.COMPLETE, "85xo")
    assert cache.is_complete("key")
    # missing file -> not complete
    cache.mark("key2", "https://x/v2.mp4", tmp_path / "gone.mp4", CacheStatus.COMPLETE)
    assert not cache.is_complete("key2")


def test_download_cache_persists(tmp_path: Path) -> None:
    path = tmp_path / "dl.json"
    cache = DownloadCacheManager(path)
    cache.mark("k", "https://x/v.mp4", tmp_path / "a.mp4", CacheStatus.FAILED, "85xo")
    reloaded = DownloadCacheManager(path)
    entry = reloaded.get("k")
    assert entry is not None
    assert entry["status"] == CacheStatus.FAILED.value
