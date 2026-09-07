from __future__ import annotations

import importlib
from pathlib import Path

fast = importlib.import_module("dler_kun.engines.85xo.fast")
downloader = importlib.import_module("dler_kun.engines.85xo.xo_dler.downloader")
models = importlib.import_module("dler_kun.engines.85xo.xo_dler.models")


def test_parallel_download_keeps_existing_and_reserves_duplicate_names(
    tmp_path: Path, monkeypatch
) -> None:
    existing = tmp_path / "same.mp4"
    existing.write_bytes(b"already-downloaded")
    items = [
        models.MediaItem("https://cdn.example/same.mp4", "https://85xo.example/v/1/"),
        models.MediaItem("https://other.example/same.mp4", "https://85xo.example/v/2/"),
    ]
    config = downloader.DownloadConfig(output_dir=tmp_path, skip_existing=True)

    def fake_download(item, target, *_args, **_kwargs):
        target.write_bytes(item.url.encode())
        return True

    monkeypatch.setattr(fast, "download_item_robust", fake_download)

    result = fast.download_existing_items_parallel(items, config, max_workers=2)

    assert existing.read_bytes() == b"already-downloaded"
    assert tmp_path.joinpath("same-2.mp4").exists()
    assert result == [existing, tmp_path / "same-2.mp4"]


def test_download_item_progress_does_not_stat_part_after_rename(
    tmp_path: Path, monkeypatch
) -> None:
    item = models.MediaItem(
        "https://cdn.example/video.mp4", "https://85xo.example/v/1/"
    )
    target = tmp_path / "video.mp4"
    config = downloader.DownloadConfig(output_dir=tmp_path)
    progress: list[tuple[int, float | None]] = []

    def fake_curl(_curl, _url, output_path, *_args, **_kwargs):
        output_path.write_bytes(b"123456")

    monkeypatch.setattr(fast, "download_with_curl", fake_curl)
    monkeypatch.setattr(fast, "probe_content_length", lambda *_args: None)

    ok = fast.download_item_robust(
        item,
        target,
        config,
        read_timeout_seconds=1,
        attempts=1,
        curl_path="curl",
        cache=None,
        cache_key="key",
        on_progress=lambda done, total: progress.append((done, total)),
    )

    assert ok is True
    assert target.read_bytes() == b"123456"
    assert not target.with_suffix(".mp4.part").exists()
    assert progress[-1] == (6, None)
