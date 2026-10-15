from pathlib import Path
from types import SimpleNamespace

from dler_kun.engines.mixixxx import adapter, fast
from dler_kun.models import CrawlRequest, DownloadRequest, JobStatus


def test_hls_concat_list_uses_actual_successful_segment_files(tmp_path, monkeypatch):
    session = object.__new__(fast.MixiSession)
    session.ffmpeg_path = "ffmpeg"
    monkeypatch.setattr(session, "_capture_m3u8", lambda _url: "https://cdn/playlist.m3u8")
    monkeypatch.setattr(session, "_resolve_segments", lambda _url: ["0.ts", "1.ts", "2.ts"])
    monkeypatch.setattr(
        session,
        "_load_resource_many",
        lambda urls, _concurrency: {
            urls[0]: (200, b"first"),
            urls[2]: (200, b"third"),
        },
    )
    concat_list = {}

    def run_ffmpeg(args, **_kwargs):
        concat_list["text"] = Path(args[args.index("-i") + 1]).read_text()
        Path(args[-1]).write_bytes(b"video")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(fast.subprocess, "run", run_ffmpeg)

    result = session.download("https://site/embed", tmp_path / "out.mp4")

    assert result == tmp_path / "out.mp4"
    assert "seg00000.ts" in concat_list["text"]
    assert "seg00002.ts" in concat_list["text"]
    assert "seg00001.ts" not in concat_list["text"]


def test_crawl_download_with_no_successful_files_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(adapter, "discover_video_pages", lambda *_args, **_kwargs: [("https://mixi-xxx.cc/1", "one")])
    monkeypatch.setattr(adapter, "fetch_html", lambda *_args: "embed")
    monkeypatch.setattr(adapter, "extract_embed_url", lambda _html: "https://embed/1")

    class Session:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def download(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(adapter, "MixiSession", Session)
    result = adapter.MixixxxEngine().crawl(
        CrawlRequest(service="mixixxx", output_dir=tmp_path, download=True)
    )

    assert result.status is JobStatus.FAILED
    assert result.errors == ["download_failed"]


def test_download_missing_ffmpeg_maps_to_dependency_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(adapter, "fetch_html", lambda *_args: "embed")
    monkeypatch.setattr(adapter, "extract_embed_url", lambda _html: "https://embed/1")

    class Session:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def download(self, *_args, **_kwargs):
            raise OSError("ffmpeg not found; needed to mux HLS segments")

    monkeypatch.setattr(adapter, "MixiSession", Session)
    result = adapter.MixixxxEngine().download(
        DownloadRequest(url="https://mixi-xxx.cc/1", output_dir=tmp_path)
    )

    assert result.status is JobStatus.FAILED
    assert result.errors == ["dependency_missing"]
