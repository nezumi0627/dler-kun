from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any, cast

import pytest

from dler_kun.engines.gofile.adapter import GoFileEngine
from dler_kun.engines.gofile.gofile_dl.downloader import go_file_api
from dler_kun.engines.gofile.gofile_dl.downloader.go_file_api import (
    GoFileAPI,
    _retry_after_seconds,
)
from dler_kun.models import DownloadRequest


def test_retry_after_parses_http_date(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(go_file_api.time, "time", lambda: now.timestamp())
    value = format_datetime(now + timedelta(seconds=45), usegmt=True)

    assert _retry_after_seconds({"Retry-After": value}) == 45


@pytest.mark.parametrize("value", ["NaN", "Infinity", "not a date"])
def test_malformed_retry_after_uses_safe_default(value: str) -> None:
    assert _retry_after_seconds({"Retry-After": value}) == go_file_api._RATE_LIMIT_DEFAULT_WAIT


class _Response:
    def __init__(self, status: int, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.headers = headers or {}
        self.released = False
        self.payload: dict[str, Any] = {"status": "ok", "data": {"id": "abc"}}

    def release(self) -> None:
        self.released = True

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise AssertionError(f"unexpected HTTP status {self.status}")

    async def json(self) -> dict[str, Any]:
        return self.payload


class _Session:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = iter(responses)
        self.calls = 0

    async def get(self, *_args: Any, **_kwargs: Any) -> _Response:
        self.calls += 1
        return next(self.responses)


def _api(session: _Session) -> GoFileAPI:
    return _TestAPI(cast(Any, session))


class _TestAPI(GoFileAPI):
    async def _get_account_token(self) -> str:
        return "token"

    async def _get_wt_salt(self) -> str:
        return "salt"


def test_429_waits_full_server_delay_before_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _Response(429, {"Retry-After": "7"})
    second = _Response(200)
    session = _Session([first, second])
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(go_file_api.asyncio, "sleep", sleep)
    assert asyncio.run(_api(session).fetch_content("abc")) == {"id": "abc"}
    assert waits == [7]
    assert first.released


def test_retryable_server_error_releases_response(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _Response(503)
    second = _Response(200)
    session = _Session([first, second])

    async def sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(go_file_api.asyncio, "sleep", sleep)
    asyncio.run(_api(session).fetch_content("abc"))
    assert first.released


def test_429_above_auto_wait_ceiling_stops_without_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _Response(429, {"Retry-After": "121"})
    session = _Session([response])

    async def unexpected_sleep(_seconds: float) -> None:
        pytest.fail("must not sleep or retry beyond the automatic wait ceiling")

    monkeypatch.setattr(go_file_api.asyncio, "sleep", unexpected_sleep)
    with pytest.raises(ValueError, match="121") as caught:
        asyncio.run(_api(session).fetch_content("abc"))
    assert getattr(caught.value, "retry_after", None) == 121
    assert session.calls == 1
    assert response.released


def test_adapter_maps_rate_limit_to_common_network_error() -> None:
    engine = GoFileEngine()
    request = DownloadRequest(
        url="https://gofile.io/d/abc", output_dir=Path(".")
    )
    result = engine._download_result_from_payload(
        request,
        {"status": "error", "message": "Rate limited (HTTP 429): retry after 121s"},
    )

    assert result.errors == ["network_error"]
    assert "121s" in result.message


def test_adapter_maps_api_rate_limit_code_to_common_network_error() -> None:
    engine = GoFileEngine()
    request = DownloadRequest(
        url="https://gofile.io/d/abc", output_dir=Path(".")
    )
    result = engine._download_result_from_payload(
        request,
        {"status": "error", "message": "API rejected request", "errors": ["error-rateLimit"]},
    )

    assert result.errors == ["network_error"]
