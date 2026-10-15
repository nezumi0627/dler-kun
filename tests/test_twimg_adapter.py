import subprocess
from pathlib import Path

from dler_kun.engines.twimg.adapter import TwimgEngine
from dler_kun.models import DownloadRequest, JobStatus


def _request(output_dir: Path) -> DownloadRequest:
    return DownloadRequest(
        url="https://cdn.example.test/item.mp4",
        output_dir=output_dir,
        engine_id="twimg",
    )


def test_success_reports_media_files_created_by_vendor_tool(
    tmp_path: Path, monkeypatch
) -> None:
    script = tmp_path / "download_twitter_media.py"
    script.touch()
    output_dir = tmp_path / "output"
    media = output_dir / "channel" / "video.mp4"

    def fake_run(command, **_kwargs):
        media.parent.mkdir(parents=True)
        media.write_bytes(b"video")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("dler_kun.engines.twimg.adapter.subprocess.run", fake_run)
    result = TwimgEngine(tmp_path).download(_request(output_dir))

    assert result.status == JobStatus.SUCCESS
    assert result.files == [str(media)]


def test_vendor_success_without_media_is_not_reported_as_download_success(
    tmp_path: Path, monkeypatch
) -> None:
    script = tmp_path / "download_twitter_media.py"
    script.touch()

    monkeypatch.setattr(
        "dler_kun.engines.twimg.adapter.subprocess.run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, stdout="no files", stderr=""
        ),
    )
    result = TwimgEngine(tmp_path).download(_request(tmp_path / "output"))

    assert result.status == JobStatus.FAILED
    assert result.errors == ["download_failed"]


def test_missing_external_dependency_returns_common_error(
    tmp_path: Path, monkeypatch
) -> None:
    script = tmp_path / "download_twitter_media.py"
    script.touch()

    def missing_tool(*_args, **_kwargs):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr("dler_kun.engines.twimg.adapter.subprocess.run", missing_tool)
    result = TwimgEngine(tmp_path).download(_request(tmp_path / "output"))

    assert result.status == JobStatus.FAILED
    assert result.errors == ["dependency_missing"]
