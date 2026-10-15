"""Resolve one media plan, then transfer it through shared infrastructure."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from dler_kun2.domain.contracts import DownloadRequest
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import DownloadResult
from dler_kun2.domain.plans import DownloadPlan
from dler_kun2.domain.types import EngineOptions
from dler_kun2.routing.registry import EngineRegistry, RouteError


class TransferService(Protocol):
    async def transfer(self, plan: DownloadPlan, output_dir: Path) -> Path: ...


async def download(url: str, output_dir: Path, registry: EngineRegistry, transfer: TransferService | None = None, options: EngineOptions | None = None) -> DownloadResult:
    engine = registry.resolve(url)
    if not engine.capabilities.download:
        raise RouteError(EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, "download is unsupported"))
    if transfer is None:
        raise RouteError(EngineError(ErrorCode.DEPENDENCY_MISSING, "transfer service is pending"))
    plan = await engine.resolve_download(DownloadRequest(url, options or {}))
    path = await transfer.transfer(plan, output_dir)
    return DownloadResult(output_paths=(path,), requested=1, discovered=1, completed=1)
