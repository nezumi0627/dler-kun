"""Routes backed by current public page-contract evidence."""

from __future__ import annotations

from urllib.parse import urlsplit

from dler_kun2.domain.contracts import Engine
from dler_kun2.engines.gofile.adapter import GoFileEngine
from dler_kun2.engines.gofile.client import GoFileClient
from dler_kun2.engines.linkex.adapter import LinkexEngine
from dler_kun2.engines.linkex.client import LinkexClient
from dler_kun2.engines.mixixxx.adapter import MixixxxEngine
from dler_kun2.engines.videy.adapter import VideyEngine
from dler_kun2.engines.xo85.adapter import Xo85Engine
from dler_kun2.infrastructure.http.client import HttpRuntime

from .registry import EngineRegistry
from .rules import RouteRule


def build_registry(registry: EngineRegistry | None = None, *, videy: Engine | None = None, xo85: Engine | None = None, http: HttpRuntime | None = None) -> EngineRegistry:
    registry = registry or EngineRegistry()
    runtime = http or HttpRuntime()
    registry.register(GoFileEngine(GoFileClient(runtime)), [RouteRule("gofile", ("gofile.io", "www.gofile.io"))])
    registry.register(videy or VideyEngine(runtime), [RouteRule("videy", ("videy.co", "www.videy.co"))])
    registry.register(xo85 or Xo85Engine(runtime), [RouteRule("85xo", ("85po.net", "www.85po.net"))])
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
    registry.register(
        MixixxxEngine(runtime),
        [RouteRule("mixixxx", ("mixi-xxx.cc", "www.mixi-xxx.cc", "jav-mixi.cc", "www.jav-mixi.cc"))],
    )
    registry.http_runtime = runtime
    # Twimg aliases remain quarantined until page/API evidence is representative.
    return registry
