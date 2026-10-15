"""Crawl plans and optionally send them to the shared transfer service."""

from __future__ import annotations

from pathlib import Path

from dler_kun2.application.download import TransferService
from dler_kun2.domain.contracts import CrawlRequest
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import CrawlResult
from dler_kun2.domain.types import EngineOptions
from dler_kun2.routing.registry import EngineRegistry, RouteError


async def crawl(engine_id: str, seeds: tuple[str, ...], days: int | None, output_dir: Path, registry: EngineRegistry, transfer: TransferService | None = None, *, download_items: bool = False, options: EngineOptions | None = None) -> CrawlResult:
    engine = registry.get(engine_id)
    if not engine.capabilities.crawl:
        raise RouteError(EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, "crawl is unsupported"))
    result = await engine.crawl(CrawlRequest(engine_id, seeds, days, options or {}))
    if not download_items:
        return result
    if transfer is None:
        raise RouteError(EngineError(ErrorCode.DEPENDENCY_MISSING, "transfer service is pending"))
    paths = tuple([await transfer.transfer(plan, output_dir) for plan in result.plans])
    return CrawlResult(plans=result.plans, output_paths=result.output_paths + paths, requested=result.requested, discovered=result.discovered, completed=result.completed + len(paths), unavailable=result.unavailable, errors=result.errors)
