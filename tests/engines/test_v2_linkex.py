import asyncio
import hashlib

import pytest

from dler_kun2.domain.contracts import DownloadRequest
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.engines.linkex.adapter import LinkexEngine
from dler_kun2.engines.linkex.client import LinkexClient
from dler_kun2.engines.linkex.parser import parse_page


def test_parser_handles_malformed_items_and_signed_url_shape():
    page = parse_page({"code": 0, "data": {"list": [{"id": "a", "name": "clip.mp4", "url": "https://cdn.example/clip.mp4?sig=secret", "type": "file"}], "total": 1}})
    assert page.items[0].media_url is not None and page.items[0].media_url.endswith("sig=secret")
    assert page.total == 1
    with pytest.raises(EngineError) as error:
        parse_page({"code": 0, "data": {"list": [None]}})
    assert error.value.code is ErrorCode.NETWORK_ERROR


def test_linkex_signing_matches_v1_algorithm_and_does_not_log_key():
    key = "test-api-key"
    client = LinkexClient(object(), key, clock=lambda: 1234)  # type: ignore[arg-type]
    path = "/api/drive/v1/share/get?share_token=ABCD"
    headers = client._headers(path)
    base = {"Content-Type": "application/json", "X-LinkInflu-App": "linkex", "X-LinkInflu-App-Lang": "ja", "X-LinkInflu-Ts": "1234"}
    hashed = hashlib.md5("&".join(f"{name.lower()}={value}" for name, value in sorted(base.items())).encode()).hexdigest()
    expected = hashlib.md5(f"path={path}&header={hashed}&body=&key={key}".encode()).hexdigest()
    assert headers["X-LinkInflu-Sign"] == expected
    assert key not in repr(headers)


def test_recursive_pages_preserve_partial_results_and_hide_share_token():
    class Client:
        @staticmethod
        def share_token(url):
            return "PRIVATE_TOKEN"

        async def validate_share(self, token):
            assert token == "PRIVATE_TOKEN"

        async def list_children(self, token, parent, page, page_size=100):
            if parent is None:
                if page == 1:
                    return parse_page({"code": 0, "data": {"list": [{"id": "folder", "type": "dir"}, {"id": "f1", "name": "same.mp4", "url": "https://cdn.test/one.mp4"}], "total": 101}})
                if page == 2:
                    raise EngineError(ErrorCode.NETWORK_ERROR, "page failed")
            if parent == "folder":
                return parse_page({"code": 0, "data": {"list": [{"id": "f2", "name": "same.mp4", "url": "https://cdn.test/two.mp4"}], "total": 1}})
            return parse_page({"code": 0, "data": {"list": [], "total": 0}})

    engine = LinkexEngine(Client())
    result = asyncio.run(engine.resolve_many(DownloadRequest("https://l2e.click/i/PRIVATE_TOKEN")))
    assert len(result.plans) == 2
    assert result.discovered == 3
    assert result.errors[0].code is ErrorCode.NETWORK_ERROR
    assert all("PRIVATE_TOKEN" not in str(plan.to_dict()) for plan in result.plans)
    assert all("sig" not in str(plan.to_dict()) for plan in result.plans)
