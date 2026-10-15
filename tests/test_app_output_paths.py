import importlib
from concurrent.futures import ThreadPoolExecutor as RealThreadPoolExecutor
from pathlib import Path
from threading import Lock

from dler_kun.app import DlerKunApp, _download_id_from_url, _download_ids_for_urls
from dler_kun.models import DownloadResult, EngineCapability, JobStatus


class RecordingEngine:
    engine_id = "recording"
    display_name = "Recording"
    capabilities = EngineCapability()

    def __init__(self) -> None:
        self.output_dirs: list[Path] = []
        self.lock = Lock()

    def download(self, request):
        with self.lock:
            self.output_dirs.append(request.output_dir)
        return DownloadResult(
            job_id=request.job_id,
            engine_id=self.engine_id,
            status=JobStatus.SUCCESS,
        )


def _app(tmp_path: Path, monkeypatch) -> tuple[DlerKunApp, RecordingEngine]:
    monkeypatch.setattr(DlerKunApp, "_install_sigint_handler", lambda self: None)
    app = DlerKunApp(tmp_path / "config.json", live_progress=False)
    engine = RecordingEngine()
    monkeypatch.setattr(app.factory, "detect", lambda _url: engine)
    return app, engine


def test_download_id_distinguishes_host_path_and_query() -> None:
    urls = [
        "https://one.example/video.mp4",
        "https://two.example/video.mp4",
        "https://one.example/other/video.mp4",
        "https://one.example/video.mp4?token=one",
        "https://one.example/video.mp4?token=two",
    ]

    ids = [_download_id_from_url(url) for url in urls]

    assert len(set(ids)) == len(urls)


def test_download_id_is_safe_and_does_not_expose_query_values() -> None:
    url = "https://example.test/CON:?.mp4?token=private-value"

    identity = _download_id_from_url(url)

    assert identity is not None
    assert len(identity) <= 255
    assert all(char not in identity for char in '<>:"/\\|?*')
    assert "private-value" not in identity


def test_download_ids_resolve_a_batch_digest_collision(monkeypatch) -> None:
    monkeypatch.setattr("dler_kun.app._download_id_from_url", lambda _url: "same-id")
    urls = ["https://one.example/a", "https://two.example/a"]

    ids = _download_ids_for_urls(urls)

    assert ids[urls[0]] != ids[urls[1]]


def test_download_urls_deduplicates_exact_urls_before_parallel_work(
    tmp_path: Path, monkeypatch
) -> None:
    app, engine = _app(tmp_path, monkeypatch)
    url = "https://one.example/video.mp4?token=one"

    results = app.download_urls(
        [url, url], tmp_path / "downloads", {"parallel_urls": 2}
    )

    assert len(results) == 2
    assert len(engine.output_dirs) == 1
    assert len(set(engine.output_dirs)) == 1


def test_parallel_urls_with_same_basename_get_distinct_output_directories(
    tmp_path: Path, monkeypatch
) -> None:
    app, engine = _app(tmp_path, monkeypatch)
    urls = [
        "https://one.example/video.mp4?token=one",
        "https://two.example/video.mp4?token=one",
        "https://one.example/video.mp4?token=two",
    ]

    results = app.download_urls(urls, tmp_path / "downloads", {"parallel_urls": 3})

    assert len(results) == len(urls)
    assert len(engine.output_dirs) == len(urls)
    assert len(set(engine.output_dirs)) == len(urls)


def test_god_uses_the_requested_parallel_url_count(tmp_path: Path, monkeypatch) -> None:
    app, _engine = _app(tmp_path, monkeypatch)
    app_module = importlib.import_module("dler_kun.app")
    worker_counts: list[int] = []

    class RecordingExecutor:
        def __init__(self, max_workers: int) -> None:
            worker_counts.append(max_workers)
            self.pool = RealThreadPoolExecutor(max_workers=max_workers)

        def __enter__(self):
            self.pool.__enter__()
            return self

        def __exit__(self, *args):
            return self.pool.__exit__(*args)

        def map(self, *args, **kwargs):
            return self.pool.map(*args, **kwargs)

    monkeypatch.setattr(app_module, "ThreadPoolExecutor", RecordingExecutor)
    urls = [f"https://example.test/{index}.mp4" for index in range(8)]

    app.download_urls(urls, tmp_path / "downloads", {"god": True})

    assert worker_counts == [8]
