"""Ranking use case with the same optional transfer boundary as crawl."""

from __future__ import annotations

from pathlib import Path

from dler_kun2.application.download import TransferService, transfer_plans
from dler_kun2.domain.contracts import CrawlRequest
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import CrawlResult
from dler_kun2.domain.types import EngineOptions, int_option
from dler_kun2.routing.registry import EngineRegistry, RouteError


async def ranking(engine_id: str, seeds: tuple[str, ...], days: int | None, output_dir: Path, registry: EngineRegistry, transfer: TransferService | None = None, *, download_items: bool = False, options: EngineOptions | None = None) -> CrawlResult:
    engine = registry.get(engine_id)
    if not engine.capabilities.ranking:
        raise RouteError(EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, "ranking is unsupported"))
    try:
        result = await engine.ranking(CrawlRequest(engine_id, seeds, days, options or {}))
    except EngineError as exc:
        raise RouteError(exc) from exc
    if not download_items:
        return result
    if transfer is None:
        raise RouteError(EngineError(ErrorCode.DEPENDENCY_MISSING, "transfer service is pending"))
    settings = options or {}
    try:
        concurrency = int_option(settings, "parallel_downloads", 4)
    except (TypeError, ValueError) as exc:
        raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "parallel download count must be an integer")) from exc
    paths, errors = await transfer_plans(result.plans, output_dir, transfer, settings, concurrency=concurrency)
    return CrawlResult(plans=result.plans, output_paths=result.output_paths + paths, requested=result.requested, discovered=result.discovered, completed=result.completed + len(paths), unavailable=result.unavailable, errors=result.errors + errors)
