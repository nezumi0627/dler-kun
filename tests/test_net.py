import subprocess

import pytest

from dler_kun.net import CurlDownloadError, fetch_text


def test_fetch_text_passes_timeout_to_curl_process(monkeypatch) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="page", stderr="")

    monkeypatch.setattr("dler_kun.net.subprocess.run", fake_run)

    assert fetch_text("https://example.test", timeout_seconds=2.5) == "page"
    assert captured["timeout"] == 2.5


def test_fetch_text_maps_process_timeout_to_download_error(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr("dler_kun.net.subprocess.run", fake_run)

    with pytest.raises(CurlDownloadError, match="timed out"):
        fetch_text("https://example.test", timeout_seconds=0.1)
