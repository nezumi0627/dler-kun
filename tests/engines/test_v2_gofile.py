import asyncio
import json

import pytest

from dler_kun2.domain.contracts import DownloadRequest
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.engines.gofile.adapter import GoFileEngine
from dler_kun2.engines.gofile.client import GoFileClient
from dler_kun2.engines.gofile.parser import content_id, parse_content
from dler_kun2.engines.gofile.token_store import GuestTokenStore


def test_content_id_and_api_response_parser():
    assert content_id("https://gofile.io/d/AbC123") == "AbC123"
    with pytest.raises(EngineError) as invalid:
        content_id("https://evil.example/d/AbC123")
    assert invalid.value.code is ErrorCode.INVALID_REQUEST
    items = parse_content({"status": "ok", "data": {"type": "folder", "children": {
        "one": {"id": "one", "name": "../same.mp4", "type": "file", "link": "https://cdn.test/signed.mp4?token=hidden", "size": 4},
        "two": {"id": "two", "name": "private", "type": "file", "link": "javascript:alert(1)"},
    }}})
    assert items[0].media_url and "hidden" in items[0].media_url
    assert items[1].media_url is None
    with pytest.raises(EngineError) as limited:
        parse_content({"status": "error-rateLimit", "data": {}})
    assert limited.value.code is ErrorCode.RATE_LIMITED


def test_nested_discovery_preserves_successes_and_unavailable_count():
    class Client:
        async def content(self, content_id: str, *, password: str | None = None, page: int = 1, page_size: int = 1000):
            if content_id == "ROOT":
                return {"status": "ok", "data": {"type": "folder", "children": {
                    "folder": {"id": "SUB", "name": "folder", "type": "folder"},
                    "file": {"id": "FILE", "name": "same.mp4", "type": "file", "link": "https://cdn.test/one.mp4", "size": 100},
                    "missing": {"id": "MISS", "name": "missing", "type": "file"},
                }}}
            if content_id == "SUB":
                return {"status": "ok", "data": {"type": "folder", "children": {
                    "file": {"id": "FILE2", "name": "same.mp4", "type": "file", "link": "https://cdn.test/two.mp4"},
                }}}
            raise AssertionError(content_id)

    result = asyncio.run(GoFileEngine(Client()).resolve_many(DownloadRequest("https://gofile.io/d/ROOT")))
    assert result.discovered == 4
    assert result.unavailable == 1
    assert len(result.plans) == 2
    assert {plan.suggested_name for plan in result.plans} == {"same.mp4"}
    assert {plan.metadata["relative_dir"] for plan in result.plans} == {"", "folder"}
    assert all("token" not in str(plan.to_dict()) for plan in result.plans)


def test_client_creates_and_reuses_one_persisted_guest_token(tmp_path):
    calls = []

    class Response:
        headers = {}

        async def json(self):
            return {"status": "ok", "data": {"token": "guest-secret"}}

    class Http:
        async def request(self, method: str, url: str, **kwargs) -> Response:
            calls.append((method, url, kwargs))
            return Response()

    store = GuestTokenStore(tmp_path / "token.json")
    client = GoFileClient(Http(), store, clock=lambda: 1_700_000_000)
    assert asyncio.run(client.account_token()) == "guest-secret"
    assert asyncio.run(GoFileClient(Http(), store).account_token()) == "guest-secret"
    assert len(calls) == 1
    assert "guest-secret" not in json.dumps(calls)
    if __import__("os").name != "nt":
        assert (tmp_path / "token.json").stat().st_mode & 0o777 == 0o600


def test_page_api_error_is_rate_limited_and_not_retried():
    class Response:
        async def json(self):
            return {"status": "error-rateLimit", "data": None}

    class Client:
        async def content(self, content_id: str, *, password=None, page=1, page_size=1000):
            return await Response().json()

    result = asyncio.run(GoFileEngine(Client()).resolve_many(DownloadRequest("https://gofile.io/d/ROOT")))
    assert result.errors[0].code is ErrorCode.RATE_LIMITED


def test_client_preserves_retry_after_and_does_not_retry(tmp_path):
    calls = []

    class Response:
        headers = {"Retry-After": "73"}

        async def json(self):
            return {"status": "error-rateLimit", "errors": ["error-rateLimit"]}

    class Http:
        async def request(self, method: str, url: str, **kwargs) -> Response:
            calls.append((method, url))
            return Response()

    client = GoFileClient(Http(), GuestTokenStore(tmp_path / "unused.json"))
    client._token = "configured-token"
    with pytest.raises(EngineError) as error:
        asyncio.run(client.content("abc"))
    assert error.value.code is ErrorCode.RATE_LIMITED
    assert error.value.retry_after == 73
    assert len(calls) == 1

