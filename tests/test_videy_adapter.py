from pathlib import Path

from dler_kun.engines.videy.adapter import VideyEngine
from dler_kun.models import DownloadRequest, JobStatus


def test_video_twitter_it_player_uses_embedded_videy_cdn_url(
    tmp_path: Path, monkeypatch
) -> None:
    engine = VideyEngine()
    request = DownloadRequest(
        url="https://video.twimg.it.com/lZwuUiqZ1.mp4",
        output_dir=tmp_path,
        engine_id="videy",
    )
    downloaded: list[str] = []

    monkeypatch.setattr(
        engine,
        "_fetch_page",
        lambda *_args, **_kwargs: '<source src="https://cdn.videy.co/lZwuUiqZ1.mp4" type="video/mp4">',
    )
    monkeypatch.setattr(
        engine,
        "_download",
        lambda vid, dest, **_kwargs: (downloaded.append(vid), dest.write_bytes(b"mp4")),
    )

    assert engine.detect(request.url)
    result = engine.download(request)

    assert result.status == JobStatus.SUCCESS
    assert downloaded == ["lZwuUiqZ1"]
    assert result.files == [str(tmp_path / "lZwuUiqZ1.mp4")]
