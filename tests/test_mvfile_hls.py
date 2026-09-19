from pathlib import Path

from dler_kun.engines.mvfile import hls
from dler_kun.net import build_curl_command


def test_target_mp4_path_preserves_non_mp4_source_extension() -> None:
    output = Path("downloads")

    assert hls.target_mp4_path(output, "clip.mov").name == "clip.mov.mp4"
    assert hls.target_mp4_path(output, "clip.mp4").name == "clip.mp4"
    assert hls.target_mp4_path(output, "ahoo(37).mov").name == "ahoo_37_.mov.mp4"


def test_curl_download_retries_empty_response(monkeypatch, tmp_path) -> None:
    calls = 0

    def fake_curl_download(url, output_path, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise hls.CurlDownloadError("curl exit 0")
        Path(output_path).write_bytes(b"ok")

    monkeypatch.setattr(hls, "curl_download", fake_curl_download)
    monkeypatch.setattr(hls.time, "sleep", lambda _: None)

    output = tmp_path / "segment.ts"
    hls._curl_download(
        "curl",
        "https://example.invalid/segment.ts",
        output,
        referer="https://cdn2.image-share.cc/k3KlOo",
        timeout_seconds=30,
    )

    assert calls == 3
    assert output.read_bytes() == b"ok"


def test_hls_curl_command_disables_small_playlist_stall_guard() -> None:
    command = build_curl_command(
        "https://example.invalid/playlist.m3u8",
        "playlist.m3u8",
        speed_limit_bytes_per_sec=0,
    )

    assert "--speed-limit" not in command
