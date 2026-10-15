"""Routes backed by current public page-contract evidence."""

from __future__ import annotations

from dler_kun2.domain.contracts import Engine
from dler_kun2.engines.videy.adapter import VideyEngine

from .registry import EngineRegistry
from .rules import RouteRule


def build_registry(registry: EngineRegistry | None = None, *, videy: Engine | None = None) -> EngineRegistry:
    registry = registry or EngineRegistry()
    registry.register(videy or VideyEngine(), [RouteRule("videy", ("videy.co",))])
    # Twimg aliases remain quarantined until page/API evidence is representative.
    return registry
