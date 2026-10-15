"""CLI command handlers call application services, not engine internals."""

from __future__ import annotations

import asyncio
from pathlib import Path

from dler_kun2.application.crawl import crawl
from dler_kun2.application.download import download
from dler_kun2.application.ranking import ranking
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.infrastructure.state.config import ConfigStore
from dler_kun2.infrastructure.storage.transfer import TransferService
from dler_kun2.routing.registry import EngineRegistry, RouteError


def run_command(command: str, target: str | None, registry: EngineRegistry, *, output_dir: Path, download_items: bool = False, seeds: tuple[str, ...] = (), days: int | None = None, save_config: bool = False) -> object:
    runtime = registry.http_runtime

    def execute(coroutine):
        async def managed():
            try:
                return await coroutine
            finally:
                if runtime is not None:
                    await runtime.close()

        return asyncio.run(managed())

    transfer = TransferService(runtime) if runtime is not None else None
    if command == "sites":
        return {"sites": registry.sites()}
    if command == "detect":
        if target is None:
            raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "URL is required"))
        engine = registry.resolve(target)
        return {"engine_id": engine.engine_id}
    if command == "config":
        config = ConfigStore()
        if save_config:
            config.save()
        return {"config": config.as_dict(), "saved": save_config}
    if command == "download":
        if target is None:
            raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "URL is required"))
        return execute(download(target, output_dir, registry, transfer))
    if command in {"crawl", "ranking"}:
        if target is None:
            raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "service is required"))
        use_case = crawl if command == "crawl" else ranking
        return execute(use_case(target, seeds, days, output_dir, registry, transfer, download_items=download_items))
    if command in {"jobs", "cancel", "config"}:
        return EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, f"{command} is pending infrastructure migration")
    raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "unknown command"))
