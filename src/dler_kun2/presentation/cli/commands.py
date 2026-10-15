"""CLI command handlers call application services, not engine internals."""

from __future__ import annotations

import asyncio
from pathlib import Path

from dler_kun2.application.crawl import crawl
from dler_kun2.application.download import download
from dler_kun2.application.ranking import ranking
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.routing.registry import EngineRegistry, RouteError


def run_command(command: str, target: str | None, registry: EngineRegistry, *, output_dir: Path, download_items: bool = False, seeds: tuple[str, ...] = (), days: int | None = None) -> object:
    if command == "sites":
        return {"sites": registry.sites()}
    if command == "detect":
        if target is None:
            raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "URL is required"))
        engine = registry.resolve(target)
        return {"engine_id": engine.engine_id}
    if command == "download":
        if target is None:
            raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "URL is required"))
        return asyncio.run(download(target, output_dir, registry))
    if command in {"crawl", "ranking"}:
        if target is None:
            raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "service is required"))
        use_case = crawl if command == "crawl" else ranking
        return asyncio.run(use_case(target, seeds, days, output_dir, registry, download_items=download_items))
    if command in {"jobs", "cancel", "config"}:
        return EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, f"{command} is pending infrastructure migration")
    raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "unknown command"))
