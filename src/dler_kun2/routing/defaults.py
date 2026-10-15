"""Routes backed by current public page-contract evidence."""

from __future__ import annotations

from dler_kun2.domain.contracts import Engine
from dler_kun2.engines.videy.adapter import VideyEngine
from dler_kun2.engines.xo85.adapter import Xo85Engine
from dler_kun2.infrastructure.http.client import HttpRuntime

from .registry import EngineRegistry
from .rules import RouteRule


def build_registry(registry: EngineRegistry | None = None, *, videy: Engine | None = None, xo85: Engine | None = None, http: HttpRuntime | None = None) -> EngineRegistry:
    registry = registry or EngineRegistry()
    runtime = http or HttpRuntime()
    registry.register(videy or VideyEngine(runtime), [RouteRule("videy", ("videy.co", "www.videy.co"))])
    registry.register(xo85 or Xo85Engine(runtime), [RouteRule("85xo", ("85po.net", "www.85po.net"))])
    registry.http_runtime = runtime
    # Twimg aliases remain quarantined until page/API evidence is representative.
    return registry
