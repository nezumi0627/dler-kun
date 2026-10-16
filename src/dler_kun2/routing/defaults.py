"""Compose the default engine registry from verified route groups."""

from __future__ import annotations

from urllib.parse import urlsplit

from dler_kun2.domain.contracts import Engine
from dler_kun2.engines.gofile.adapter import GoFileEngine
from dler_kun2.engines.gofile.client import GoFileClient
from dler_kun2.engines.gofile.ranking import is_ranking_source_url
from dler_kun2.engines.gofilerun.adapter import GofileRunEngine
from dler_kun2.engines.linkex.adapter import LinkexEngine
from dler_kun2.engines.linkex.client import LinkexClient
from dler_kun2.engines.mixixxx.adapter import MixixxxEngine
from dler_kun2.engines.mvfile.adapter import MvfileEngine
from dler_kun2.engines.mvfile.api import DEFAULT_API, Fun800Client
from dler_kun2.engines.videy.adapter import VideyEngine
from dler_kun2.engines.xo85.adapter import Xo85Engine
from dler_kun2.infrastructure.http.client import HttpRuntime

from .registry import EngineRegistry
from .rules import RouteRule

_MVFILE_HOSTS = (
    "tweetfile.com", "www.tweetfile.com", "gofile.website", "www.gofile.website",
    "image-share.cc", "www.image-share.cc", "cdn2.image-share.cc", "tweetplay.com",
    "www.tweetplay.com", "imagedist.com", "www.imagedist.com", "gofile.rocks",
    "www.gofile.rocks", "gofile.bar", "www.gofile.bar", "gofile.pl", "www.gofile.pl",
    "twimg-media.com", "www.twimg-media.com", "cdn1.twimg-media.com",
    "www.cdn1.twimg-media.com", "video.twimg-image.com", "www.video.twimg-image.com",
    "media-twimg.com", "www.media-twimg.com", "cdn.twimg1.com", "www.cdn.twimg1.com",
    "twimg1.com", "www.twimg1.com", "twimg-album.com", "www.twimg-album.com",
    "twfiles.com", "www.twfiles.com",
)


def _register_gofile(registry: EngineRegistry, runtime: HttpRuntime) -> None:
    registry.register(
        GoFileEngine(GoFileClient(runtime)),
        (
            RouteRule("gofile", ("gofile.io", "www.gofile.io")),
            RouteRule(
                "gofile",
                ("gofile-douga.com", "www.gofile-douga.com"),
                backend_probe=is_ranking_source_url,
            ),
            RouteRule(
                "gofile",
                ("gofilelab.com", "www.gofilelab.com"),
                backend_probe=is_ranking_source_url,
            ),
        ),
    )


def _register_mvfile(
    registry: EngineRegistry, runtime: HttpRuntime, api_base: str | None
) -> None:
    client = Fun800Client(runtime, api_base or DEFAULT_API)
    registry.register(MvfileEngine(client), [RouteRule("mvfile", _MVFILE_HOSTS)])


def _register_gofilerun(
    registry: EngineRegistry,
    runtime: HttpRuntime,
    api_base: str | None,
    mvfile_api_base: str | None,
) -> None:
    client = Fun800Client(runtime, api_base or mvfile_api_base or DEFAULT_API)
    registry.register(
        GofileRunEngine(client),
        [RouteRule("gofilerun", ("gofile.run", "www.gofile.run"))],
    )


def _register_videy(registry: EngineRegistry, runtime: HttpRuntime, engine: Engine | None) -> None:
    registry.register(
        engine or VideyEngine(runtime),
        [
            RouteRule(
                "videy",
                ("videy.co", "www.videy.co", "video.twimg.it.com", "www.video.twimg.it.com"),
            )
        ],
    )


def _register_xo85(registry: EngineRegistry, runtime: HttpRuntime, engine: Engine | None) -> None:
    registry.register(
        engine or Xo85Engine(runtime),
        [RouteRule("85xo", ("85po.net", "www.85po.net"))],
    )


def _register_linkex(registry: EngineRegistry, runtime: HttpRuntime) -> None:
    registry.register(
        LinkexEngine(LinkexClient(runtime)),
        [
            RouteRule(
                "linkex",
                ("l2e.click", "www.l2e.click"),
                backend_probe=lambda url: urlsplit(url).path.startswith("/i/"),
            )
        ],
    )


def _register_mixixxx(registry: EngineRegistry, runtime: HttpRuntime) -> None:
    registry.register(
        MixixxxEngine(runtime),
        [
            RouteRule(
                "mixixxx",
                ("mixi-xxx.cc", "www.mixi-xxx.cc", "jav-mixi.cc", "www.jav-mixi.cc"),
            )
        ],
    )


def build_registry(
    registry: EngineRegistry | None = None,
    *,
    videy: Engine | None = None,
    xo85: Engine | None = None,
    http: HttpRuntime | None = None,
    mvfile_api_base: str | None = None,
    gofilerun_api_base: str | None = None,
) -> EngineRegistry:
    """Build routes only for backends supported by current response evidence."""
    registry = registry or EngineRegistry()
    runtime = http or HttpRuntime()
    _register_gofile(registry, runtime)
    _register_mvfile(registry, runtime, mvfile_api_base)
    _register_gofilerun(registry, runtime, gofilerun_api_base, mvfile_api_base)
    _register_videy(registry, runtime, videy)
    _register_xo85(registry, runtime, xo85)
    _register_linkex(registry, runtime)
    _register_mixixxx(registry, runtime)
    registry.http_runtime = runtime
    # Twimg's former aliases are verified Fun800 pages and belong to mvfile.
    # Keep the legacy adapter isolated until a distinct public route is proven.
    return registry
