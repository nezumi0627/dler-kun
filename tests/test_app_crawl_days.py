from pathlib import Path

from dler_kun.app import DlerKunApp
from dler_kun.models import CrawlResult, EngineCapability, JobStatus


class RecordingCrawler:
    engine_id = "85xo"
    display_name = "Recording crawler"
    capabilities = EngineCapability(crawl=True)

    def __init__(self) -> None:
        self.days: list[int] = []

    def crawl(self, request):
        self.days.append(request.days)
        return CrawlResult(
            job_id=request.job_id,
            engine_id=self.engine_id,
            status=JobStatus.SUCCESS,
        )


def _app(tmp_path: Path, monkeypatch) -> tuple[DlerKunApp, RecordingCrawler]:
    monkeypatch.setattr(DlerKunApp, "_install_sigint_handler", lambda self: None)
    app = DlerKunApp(tmp_path / "config.json", live_progress=False)
    crawler = RecordingCrawler()
    monkeypatch.setattr(app.factory, "get", lambda _service: crawler)
    return app, crawler


def test_crawl_preserves_explicit_zero_days(tmp_path: Path, monkeypatch) -> None:
    app, crawler = _app(tmp_path, monkeypatch)

    app.crawl("85xo", days=0)

    assert crawler.days == [0]


def test_crawl_defaults_days_only_when_omitted(tmp_path: Path, monkeypatch) -> None:
    app, crawler = _app(tmp_path, monkeypatch)

    app.crawl("85xo")

    assert crawler.days == [10]


def test_crawl_rejects_negative_days(tmp_path: Path, monkeypatch) -> None:
    app, crawler = _app(tmp_path, monkeypatch)

    result = app.crawl("85xo", days=-1)

    assert result["errors"] == ["invalid_request"]
    assert crawler.days == []
