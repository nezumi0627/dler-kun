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
    download_plan = getattr(engine, "download_plan", None)
    if transfer is None and not callable(download_plan):
        raise RouteError(EngineError(ErrorCode.DEPENDENCY_MISSING, "transfer service is pending"))
    paths = list(result.output_paths)
    errors = list(result.errors)
    for plan in result.plans:
        try:
            if callable(download_plan):
                paths.append(await download_plan(plan, output_dir, options=options or {}))
            else:
                paths.append(await transfer.transfer(plan, output_dir, force=bool((options or {}).get("force") or (options or {}).get("overwrite")), metadata=bool((options or {}).get("metadata"))))
        except EngineError as exc:
            errors.append(exc)
        except Exception as exc:
            from dler_kun2.infrastructure.http.client import HttpError

            code = exc.code if isinstance(exc, HttpError) else ErrorCode.DOWNLOAD_FAILED
            retry_after = exc.retry_after if isinstance(exc, HttpError) else None
            errors.append(EngineError(code, "media transfer failed", retry_after))
    return CrawlResult(plans=result.plans, output_paths=tuple(paths), requested=result.requested, discovered=result.discovered, completed=len(paths), unavailable=result.unavailable, errors=tuple(errors))
