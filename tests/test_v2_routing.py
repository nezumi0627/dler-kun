import pytest

from dler_kun.detector import ServiceDetector
from dler_kun2.domain.contracts import EngineCapabilities
from dler_kun2.domain.errors import ErrorCode
from dler_kun2.routing.registry import UNVERIFIED_HOSTS, EngineRegistry, RouteError
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
        ("gofile", "gofile.io"),
        ("gofile", "gofile-douga.com"),
        ("85xo", "85po.net"),
        ("videy", "videy.co"),
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


@pytest.mark.parametrize("host", [
    "gofilelab.com", "gofile.run", "85xo.com", "85po.com",
    "mvfile.com", "file-photo.com", "tweetfile.com", "gofile.website",
    "image-share.cc", "tweetplay.com", "imagedist.com", "gofile.rocks",
    "gofile.host", "gofile.guru", "gofile.name", "mediasplayer.com",
    "twimg-media.com", "media-twimg.com", "twimg.jp", "video.twimg.jp",
    "video.twimg-image.com", "video.twimg1.com", "cdn.twimg1.com",
    "twimg1.com", "twimg-album.com", "file-bio.com", "twfiles.com",
    "gofile.video", "gofile.trade", "gofile.bar", "gofile.pl",
    "cdn1.twimg-media.com", "video.twimg.news", "video.twimg.it.com",
    "l2e.click",
])
def test_unverified_legacy_alias_is_ambiguous(host):
    with pytest.raises(RouteError) as exc:
        EngineRegistry().resolve(f"https://{host}/item")
    assert exc.value.error.code is ErrorCode.AMBIGUOUS_SERVICE


def test_every_legacy_host_is_verified_or_quarantined():
    legacy_hosts = set().union(*(set(hosts) for hosts in ServiceDetector().supported_domains().values()))
    assert legacy_hosts == UNVERIFIED_HOSTS | {
        "gofile.io", "gofile-douga.com", "85po.net", "videy.co", "mixi-xxx.cc"
    }


def test_subdomain_of_unverified_alias_is_quarantined():
    with pytest.raises(RouteError) as exc:
        EngineRegistry().resolve("https://cdn2.image-share.cc/k3KlOo")
    assert exc.value.error.code is ErrorCode.AMBIGUOUS_SERVICE


def test_path_predicate_failure_is_typed_and_redacted_in_cli(capsys, monkeypatch):
    from dler_kun2.presentation.cli.main import main

    def fail(_path):
        raise RuntimeError("secret-path-token")

    registry = EngineRegistry()
    registry.register(FakeEngine("sample"), [RouteRule("sample", ("sample.test",), path_predicate=fail)])
    monkeypatch.setattr("dler_kun2.presentation.cli.main.EngineRegistry", lambda: registry)
    assert main(["detect", "https://sample.test/item", "--json"]) == 2
    payload = capsys.readouterr().out
    assert '"code": "ambiguous_service"' in payload
    assert "secret-path-token" not in payload


def test_unverified_unique_host_stays_quarantined_after_bare_registration():
    registry = EngineRegistry()
    registry.register(FakeEngine("linkex"), [RouteRule("linkex", ("l2e.click",))])
    with pytest.raises(RouteError) as exc:
        registry.resolve("https://l2e.click/share")
    assert exc.value.error.code is ErrorCode.AMBIGUOUS_SERVICE


def test_probe_failure_is_typed_and_does_not_expose_exception(capsys, monkeypatch):
    from dler_kun2.presentation.cli.main import main

    def fail(_url):
        raise RuntimeError("private-token")

    registry = EngineRegistry()
    registry.register(FakeEngine("twimg"), [RouteRule("twimg", ("twimg.jp",), backend_probe=fail)])
    monkeypatch.setattr("dler_kun2.presentation.cli.main.EngineRegistry", lambda: registry)
    assert main(["detect", "https://twimg.jp/item", "--json"]) == 2
    payload = capsys.readouterr().out
    assert '"code": "network_error"' in payload
    assert "private-token" not in payload


def test_disputed_host_needs_backend_probe_even_with_one_registration():
    registry = EngineRegistry()
    registry.register(FakeEngine("twimg"), [RouteRule("twimg", ("twimg.jp",))])
    with pytest.raises(RouteError) as exc:
        registry.resolve("https://twimg.jp/item")
    assert exc.value.error.code is ErrorCode.AMBIGUOUS_SERVICE

    proven = EngineRegistry()
    proven.register(FakeEngine("twimg"), [RouteRule("twimg", ("twimg.jp",), backend_probe=lambda url: "/verified/" in url)])
    assert proven.resolve("https://twimg.jp/verified/item").engine_id == "twimg"
