import pytest

from dler_kun2.domain.contracts import EngineCapabilities
from dler_kun2.domain.errors import ErrorCode
from dler_kun2.routing.registry import EngineRegistry, RouteError
from dler_kun2.routing.rules import PathPrefix, RouteRule


class FakeEngine:
    def __init__(self, engine_id: str):
        self.engine_id = engine_id
        self.capabilities = EngineCapabilities(download=True)

    async def resolve_download(self, request):
        raise NotImplementedError

    async def crawl(self, request):
        raise NotImplementedError

    async def ranking(self, request):
        raise NotImplementedError


@pytest.mark.parametrize(
    ("engine_id", "host"),
    [
        ("gofile", "gofile.io"), ("gofilerun", "gofile.run"),
        ("85xo", "85po.net"), ("mvfile", "image-share.cc"),
        ("twimg", "cdn1.twimg-media.com"), ("videy", "videy.co"),
        ("mixixxx", "mixi-xxx.cc"), ("linkex", "l2e.click"),
    ],
)
def test_registered_engine_routes_only_its_exact_host(engine_id, host):
    registry = EngineRegistry()
    registry.register(FakeEngine(engine_id), [RouteRule(engine_id, (host,))])
    assert registry.resolve(f"https://{host}/item").engine_id == engine_id
    with pytest.raises(RouteError) as exc:
        registry.resolve(f"https://evil-{host}/item")
    assert exc.value.error.code is ErrorCode.UNSUPPORTED_SERVICE


def test_shared_host_requires_proven_disjoint_paths():
    registry = EngineRegistry()
    registry.register(FakeEngine("one"), [RouteRule("one", ("shared.test",))])
    with pytest.raises(ValueError):
        registry.register(FakeEngine("two"), [RouteRule("two", ("shared.test",))])

    registry = EngineRegistry()
    registry.register(FakeEngine("one"), [RouteRule("one", ("shared.test",), PathPrefix("/one/"))])
    registry.register(FakeEngine("two"), [RouteRule("two", ("shared.test",), PathPrefix("/two/"))])
    assert registry.resolve("https://shared.test/one/1").engine_id == "one"
    with pytest.raises(RouteError) as exc:
        registry.resolve("https://shared.test/other/1")
    assert exc.value.error.code is ErrorCode.AMBIGUOUS_SERVICE


@pytest.mark.parametrize("url", ["not a url", "ftp://gofile.io/a", "https://user@gofile.io/a", "https:///x"])
def test_malformed_url_is_invalid_request(url):
    with pytest.raises(RouteError) as exc:
        EngineRegistry().resolve(url)
    assert exc.value.error.code is ErrorCode.INVALID_REQUEST


@pytest.mark.parametrize("host", ["tweetfile.com", "twimg.jp", "twimg-media.com"])
def test_unverified_legacy_overlap_is_ambiguous(host):
    with pytest.raises(RouteError) as exc:
        EngineRegistry().resolve(f"https://{host}/item")
    assert exc.value.error.code is ErrorCode.AMBIGUOUS_SERVICE


def test_disputed_host_needs_backend_probe_even_with_one_registration():
    registry = EngineRegistry()
    registry.register(FakeEngine("twimg"), [RouteRule("twimg", ("twimg.jp",))])
    with pytest.raises(RouteError) as exc:
        registry.resolve("https://twimg.jp/item")
    assert exc.value.error.code is ErrorCode.AMBIGUOUS_SERVICE

    proven = EngineRegistry()
    proven.register(FakeEngine("twimg"), [RouteRule("twimg", ("twimg.jp",), backend_probe=lambda url: "/verified/" in url)])
    assert proven.resolve("https://twimg.jp/verified/item").engine_id == "twimg"
