"""Crawl plans and optionally send them to the shared transfer service."""

from __future__ import annotations

from pathlib import Path

from dler_kun2.application.download import (
    PlanDownloader,
    TransferService,
    transfer_plans,
)
from dler_kun2.domain.contracts import CrawlRequest
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import CrawlResult
from dler_kun2.domain.types import EngineOptions, int_option
from dler_kun2.routing.registry import EngineRegistry, RouteError


async def crawl(engine_id: str, seeds: tuple[str, ...], days: int | None, output_dir: Path, registry: EngineRegistry, transfer: TransferService | None = None, *, download_items: bool = False, options: EngineOptions | None = None) -> CrawlResult:
    engine = registry.get(engine_id)
    if not engine.capabilities.crawl:
        raise RouteError(EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, "crawl is unsupported"))
    result = await engine.crawl(CrawlRequest(engine_id, seeds, days, options or {}))
    if not download_items:
        return result
    engine_downloader = engine if isinstance(engine, PlanDownloader) else None
    if transfer is None and engine_downloader is None:
        raise RouteError(EngineError(ErrorCode.DEPENDENCY_MISSING, "transfer service is pending"))
    errors = list(result.errors)
    settings = options or {}
    try:
        concurrency = int_option(settings, "parallel_downloads", 4)
    except (TypeError, ValueError) as exc:
        raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "parallel download count must be an integer")) from exc

    async def engine_download(plan):
        assert engine_downloader is not None
        return await engine_downloader.download_plan(plan, output_dir, options=settings)

    paths, transfer_errors = await transfer_plans(
        result.plans,
        output_dir,
        transfer,
        settings,
        concurrency=concurrency,
        downloader=engine_download if engine_downloader is not None else None,
    )
    errors.extend(transfer_errors)
    paths = list(result.output_paths) + list(paths)
    return CrawlResult(plans=result.plans, output_paths=tuple(paths), requested=result.requested, discovered=result.discovered, completed=len(paths), unavailable=result.unavailable, errors=tuple(errors))
