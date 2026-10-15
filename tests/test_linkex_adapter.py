from __future__ import annotations

from pathlib import Path

from dler_kun.engines.linkex.adapter import LinkexEngine
from dler_kun.models import DownloadRequest, JobStatus


def test_invalid_share_url_keeps_invalid_request_classification(tmp_path: Path) -> None:
    result = LinkexEngine().download(DownloadRequest("https://l2e.click/not-a-share", tmp_path))

    assert result.status is JobStatus.FAILED
    assert result.errors == ["invalid_request"]
