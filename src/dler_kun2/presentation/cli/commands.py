"""CLI command handlers call application services, not engine internals."""

from __future__ import annotations

import asyncio
from pathlib import Path

from dler_kun2.application.crawl import crawl
from dler_kun2.application.download import download, download_many
from dler_kun2.application.ranking import ranking
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.types import EngineOptions
from dler_kun2.infrastructure.state.config import ConfigStore
from dler_kun2.infrastructure.state.jobs import JobStore
from dler_kun2.infrastructure.state.paths import state_dir
from dler_kun2.infrastructure.storage.transfer import TransferService
from dler_kun2.routing.registry import EngineRegistry, RouteError


def run_command(command: str, target: str | None, registry: EngineRegistry, *, output_dir: Path, download_items: bool = False, seeds: tuple[str, ...] = (), days: int | None = None, save_config: bool = False, cancel_all: bool = False, targets: tuple[str, ...] | None = None, parallel_urls: int = 4, options: EngineOptions | None = None) -> object:
    runtime = registry.http_runtime

    def execute(coroutine, kind: str):
        store = JobStore(state_dir() / "jobs.sqlite3")
        job_id = store.create(kind)
        if not store.transition(job_id, "running"):
            raise RuntimeError("new job could not enter running state")

        async def managed():
            try:
                task = asyncio.create_task(coroutine)
                while True:
                    done, _ = await asyncio.wait((task,), timeout=0.1)
                    if task in done:
                        result = await task
                        store.transition(job_id, "succeeded")
                        return result
                    if await asyncio.to_thread(store.is_cancelled, job_id):
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        store.transition(job_id, "cancelled")
                        return EngineError(ErrorCode.CANCELLED, "job was cancelled")
            except asyncio.CancelledError:
                store.transition(job_id, "cancelled")
                return EngineError(ErrorCode.CANCELLED, "job was cancelled")
            except BaseException:
                store.transition(job_id, "failed")
                raise
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
    if command == "jobs":
        jobs = JobStore(state_dir() / "jobs.sqlite3").list()
        return {"jobs": [{"id": job.id, "kind": job.kind, "status": job.status, "cancel_requested": job.cancel_requested} for job in jobs]}
    if command == "cancel":
        store = JobStore(state_dir() / "jobs.sqlite3")
        if cancel_all:
            ids = store.cancel_all()
            return {"cancelled": len(ids), "job_ids": list(ids)}
        if not target:
            raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "provide JOB_ID or --all"))
        try:
            job = store.get(target)
        except KeyError as exc:
            raise RouteError(EngineError(ErrorCode.NOT_FOUND, "job was not found")) from exc
        changed = store.cancel(target)
        return {"job_id": target, "status": job.status, "cancel_requested": changed or job.cancel_requested}
    if command == "download":
        if parallel_urls < 1:
            raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "parallel URL count must be positive"))
        urls = targets or ((target,) if target is not None else ())
        if not urls:
            raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "URL is required"))
        operation = download_many(urls, output_dir, registry, transfer, options, concurrency=parallel_urls) if len(urls) > 1 else download(urls[0], output_dir, registry, transfer, options)
        return execute(operation, "download")
    if command in {"crawl", "ranking"}:
        if target is None:
            raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "service is required"))
        use_case = crawl if command == "crawl" else ranking
        return execute(use_case(target, seeds, days, output_dir, registry, transfer, download_items=download_items, options=options), command)
    raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "unknown command"))
