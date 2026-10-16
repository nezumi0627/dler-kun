import asyncio
import json

import pytest

from dler_kun2.domain.contracts import DownloadRequest
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.engines.gofile.adapter import GoFileEngine
from dler_kun2.engines.gofile.client import GoFileClient
from dler_kun2.engines.gofile.parser import content_id, parse_content
from dler_kun2.engines.gofile.ranking import fetch_ids, normalize_sources
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
    with pytest.raises(EngineError) as password:
        parse_content({"status": "ok", "data": {"type": "folder", "canAccess": False, "password": True}})
    assert password.value.code is ErrorCode.AUTH_REQUIRED
    with pytest.raises(EngineError) as expired:
        parse_content({"status": "ok", "data": {"type": "folder", "canAccess": False, "expire": True}})
    assert expired.value.code is ErrorCode.NOT_FOUND


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


def test_explicit_pagination_flag_overrides_short_page_size():
    pages = []

    class Client:
        async def content(self, content_id, *, password=None, page=1, page_size=1000):
            pages.append(page)
            item_id = f"FILE{page}"
            return {
                "status": "ok",
                "data": {
                    "type": "folder",
                    "children": {item_id: {"id": item_id, "name": f"{item_id}.mp4", "type": "file", "link": f"https://cdn.test/{item_id}.mp4"}},
                },
                "metadata": {"hasNextPage": page == 1, "totalPages": 2},
            }

    result = asyncio.run(GoFileEngine(Client()).resolve_many(DownloadRequest("https://gofile.io/d/ROOT")))
    assert pages == [1, 2]
    assert result.discovered == 2
    assert len(result.plans) == 2


def test_crawl_rejects_invalid_page_limit_before_api_calls():
    class Client:
        async def content(self, *_args, **_kwargs):
            raise AssertionError("invalid pagination must not make a request")

    engine = GoFileEngine(Client())
    with pytest.raises(EngineError) as error:
        asyncio.run(engine._discover("https://gofile.io/d/ROOT", None, max_pages=0))
    assert error.value.code is ErrorCode.INVALID_REQUEST


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
    assert "json" not in calls[0][2]
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
            calls.append((method, url, kwargs))
            return Response()

    class TokenProvider:
        async def generate(self, account_token: str):
            assert account_token == "configured-token"
            return "fresh-wt", "fresh-browser-ua", "ja-JP"

    client = GoFileClient(Http(), GuestTokenStore(tmp_path / "unused.json"), website_token_provider=TokenProvider())
    client._token = "configured-token"
    with pytest.raises(EngineError) as error:
        asyncio.run(client.content("abc"))
    assert error.value.code is ErrorCode.RATE_LIMITED
    assert error.value.retry_after == 73
    assert len(calls) == 1
    assert calls[0][2]["headers"]["X-Website-Token"] == "fresh-wt"
    assert calls[0][2]["headers"]["User-Agent"] == "fresh-browser-ua"


def test_rate_limit_http_date_uses_injected_clock(tmp_path):
    from email.utils import formatdate

    now = 1_700_000_000

    class Response:
        headers = {"Retry-After": formatdate(now + 91, usegmt=True)}

        async def json(self):
            return {"status": "error-rateLimit"}

    class Http:
        async def request(self, *_args, **_kwargs):
            return Response()

    class TokenProvider:
        async def generate(self, account_token: str):
            assert account_token == "account-token"
            return "wt", "ua", "ja"

    client = GoFileClient(Http(), GuestTokenStore(tmp_path / "unused.json"), clock=lambda: now, website_token_provider=TokenProvider())
    client._token = "account-token"
    with pytest.raises(EngineError) as error:
        asyncio.run(client.content("ROOT"))
    assert error.value.code is ErrorCode.RATE_LIMITED
    assert error.value.retry_after == 91


def test_current_website_token_fails_closed_without_supported_browser(monkeypatch):
    from dler_kun2.engines.gofile.browser_token import BrowserWebsiteTokenProvider

    monkeypatch.setattr("dler_kun2.engines.gofile.browser_token._find_browser", lambda: None)
    with pytest.raises(EngineError) as failure:
        asyncio.run(BrowserWebsiteTokenProvider().generate("account-token"))
    assert failure.value.code is ErrorCode.DEPENDENCY_MISSING


def test_browser_token_provider_calls_first_party_generator_without_interpolating_token(monkeypatch):
    import json

    import websockets.sync.client

    from dler_kun2.engines.gofile.browser_token import BrowserWebsiteTokenProvider

    class Socket:
        def __init__(self):
            self.events = []
            self.expressions = []

        def send(self, value):
            request = json.loads(value)
            expression = request.get("params", {}).get("expression", "")
            self.expressions.append(expression)
            if expression.startswith("typeof"):
                result = {"result": {"value": True}}
            elif expression:
                result = {"result": {"value": json.dumps({"wt": "fresh-token", "ua": "current-browser", "language": "ja-JP"})}}
            else:
                result = {}
            self.events.append(json.dumps({"id": request["id"], "result": result}))

        def recv(self, timeout):
            return self.events.pop(0)

        def close(self):
            pass

    class Process:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    socket = Socket()
    monkeypatch.setattr(websockets.sync.client, "connect", lambda *args, **kwargs: socket)
    monkeypatch.setattr("dler_kun2.engines.gofile.browser_token._wait_for_page", lambda *args: "ws://127.0.0.1:1234/devtools/page/1")
    monkeypatch.setattr("dler_kun2.engines.gofile.browser_token.subprocess.Popen", lambda *args, **kwargs: Process())

    result = BrowserWebsiteTokenProvider("fake-browser")._generate('account";throw 1;//')
    assert result == ("fresh-token", "current-browser", "ja-JP")
    assert '"account\\\";throw 1;//"' in socket.expressions[-1]


def test_ranking_sources_normalize_and_dedupe():
    assert normalize_sources(("new", "douga", "popular-24h")) == (
        "https://gofile-douga.com/new",
        "https://gofile-douga.com/",
        "https://gofile-douga.com/?sort=24h",
        "https://gofile-douga.com/?sort=3days",
        "https://gofilelab.com/ja/popular-24h",
    )


def test_ranking_fetch_extracts_unique_ids_and_respects_lab_age_gate():
    class Response:
        async def json(self):
            return {"items": [
                {"gofileUrl": "https://gofile.io/d/First"},
                {"gofileUrl": "https://gofile.io/d/First"},
                {"gofileUrl": "https://elsewhere.test/d/ignored"},
            ]}

        async def text(self):
            return "18歳以上 年齢確認"

    class Http:
        async def request(self, method, url, **kwargs):
            self.url = url
            return Response()

    http = Http()
    assert asyncio.run(fetch_ids(http, "https://gofile-douga.com/new", limit=17)) == ("First",)
    assert "api/new" in http.url
    assert "limit=17" in http.url
    with pytest.raises(EngineError) as gate:
        asyncio.run(fetch_ids(http, "https://gofilelab.com/ja/newest"))
    assert gate.value.code is ErrorCode.AUTH_REQUIRED


def test_engine_ranking_keeps_partial_success_when_lab_requires_age_verification():
    class Response:
        async def json(self):
            return {"items": [{"gofileUrl": "https://gofile.io/d/ROOT"}]}

        async def text(self):
            return "18歳以上 年齢確認"

    class Http:
        async def request(self, method, url, **kwargs):
            return Response()

    class Client:
        http = Http()

        async def content(self, content_id, *, password=None, page=1, page_size=1000):
            return {"status": "ok", "data": {"type": "file", "id": "ROOT", "name": "clip.mp4", "link": "https://cdn.test/clip.mp4"}}

    from dler_kun2.domain.contracts import CrawlRequest

    result = asyncio.run(GoFileEngine(Client()).ranking(CrawlRequest("gofile", (
        "https://gofile-douga.com/new", "https://gofilelab.com/ja/newest"
    ), None)))
    assert len(result.plans) == 1
    assert result.discovered == 1
    assert result.errors[0].code is ErrorCode.AUTH_REQUIRED

