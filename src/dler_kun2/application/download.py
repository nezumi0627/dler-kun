"""Resolve one media plan, then transfer it through shared infrastructure."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol, runtime_checkable

from dler_kun2.domain.contracts import DownloadRequest
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import DownloadResult
from dler_kun2.domain.plans import DownloadPlan
from dler_kun2.domain.types import EngineOptions
from dler_kun2.routing.registry import EngineRegistry, RouteError


class TransferService(Protocol):
    async def transfer(self, plan: DownloadPlan, output_dir: Path, *, force: bool = False, metadata: bool = False) -> Path: ...


@runtime_checkable
class VendorDownloader(Protocol):
    async def run_vendor(self, request: DownloadRequest, output_dir: Path) -> tuple[Path, ...]: ...


@runtime_checkable
class MultiPlanResolver(Protocol):
    async def resolve_many(self, request: DownloadRequest): ...


async def download(url: str, output_dir: Path, registry: EngineRegistry, transfer: TransferService | None = None, options: EngineOptions | None = None) -> DownloadResult:
    engine = registry.resolve(url)
    if not engine.capabilities.download:
        raise RouteError(EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, "download is unsupported"))
    request = DownloadRequest(url, options or {})
    if isinstance(engine, VendorDownloader):
        paths = await engine.run_vendor(request, output_dir)
        return DownloadResult(output_paths=paths, requested=1, discovered=len(paths), completed=len(paths))
    if transfer is None:
        raise RouteError(EngineError(ErrorCode.DEPENDENCY_MISSING, "transfer service is pending"))
    if isinstance(engine, MultiPlanResolver):
        result = await engine.resolve_many(request)
        paths: list[Path] = []
        errors = list(result.errors)
        for plan in result.plans:
            try:
                paths.append(await transfer.transfer(plan, output_dir, force=bool(request.options.get("force")), metadata=bool(request.options.get("metadata"))))
            except EngineError as exc:
                errors.append(exc)
            except Exception as exc:
                from dler_kun2.infrastructure.http.client import HttpError

                code = exc.code if isinstance(exc, HttpError) else ErrorCode.DOWNLOAD_FAILED
                retry_after = exc.retry_after if isinstance(exc, HttpError) else None
                errors.append(EngineError(code, "media transfer failed", retry_after))
        return DownloadResult(output_paths=tuple(paths), requested=result.requested, discovered=result.discovered, completed=len(paths), unavailable=result.unavailable, errors=tuple(errors))
    plan = await engine.resolve_download(request)
    path = await transfer.transfer(plan, output_dir, force=bool(request.options.get("force")), metadata=bool(request.options.get("metadata")))
    return DownloadResult(output_paths=(path,), requested=1, discovered=1, completed=1)


async def download_many(
    urls: tuple[str, ...],
    output_dir: Path,
    registry: EngineRegistry,
    transfer: TransferService | None = None,
    options: EngineOptions | None = None,
    *,
    concurrency: int = 4,
) -> DownloadResult:
    if not urls:
        raise EngineError(ErrorCode.INVALID_REQUEST, "at least one URL is required")
    if concurrency < 1:
        raise EngineError(ErrorCode.INVALID_REQUEST, "concurrency must be positive")

    semaphore = asyncio.Semaphore(concurrency)
    unique_urls = tuple(dict.fromkeys(urls))

    async def run_one(url: str) -> DownloadResult | EngineError:
        async with semaphore:
            try:
                return await download(url, output_dir, registry, transfer, options)
            except RouteError as exc:
                return exc.error
            except EngineError as exc:
                return exc
            except Exception as exc:
                from dler_kun2.infrastructure.http.client import HttpError

                if isinstance(exc, HttpError):
                    return EngineError(exc.code, "download request failed", exc.retry_after)
                return EngineError(ErrorCode.DOWNLOAD_FAILED, "download request failed")

    results = await asyncio.gather(*(run_one(url) for url in unique_urls))
    successful = [result for result in results if isinstance(result, DownloadResult)]
    errors = [result for result in results if isinstance(result, EngineError)]
    return DownloadResult(
        output_paths=tuple(path for result in successful for path in result.output_paths),
        requested=sum(result.requested for result in successful) + len(errors),
        discovered=sum(result.discovered for result in successful),
        completed=sum(result.completed for result in successful),
        unavailable=sum(result.unavailable for result in successful),
        errors=tuple(error for result in successful for error in result.errors) + tuple(errors),
    )
