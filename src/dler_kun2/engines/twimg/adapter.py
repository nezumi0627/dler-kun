"""Managed subprocess boundary for the legacy Twimg media tool."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol, cast
from urllib.parse import urlsplit

from dler_kun2.domain.contracts import (
    CrawlRequest,
    DownloadRequest,
    EngineCapabilities,
)
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import CrawlResult
from dler_kun2.domain.plans import DownloadPlan
from dler_kun2.infrastructure.storage.paths import OutputAllocator

from .parser import suggested_filename


class ManagedProcess(Protocol):
    @property
    def returncode(self) -> int | None: ...

    async def communicate(self) -> tuple[bytes, bytes]: ...

    def terminate(self) -> None: ...

    async def wait(self) -> int: ...


ProcessRunner = Callable[..., Awaitable[object]]
_MEDIA_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".jpg", ".png"}


async def _spawn(*args: str, **kwargs: object) -> object:
    return await asyncio.create_subprocess_exec(*args, **kwargs)  # type: ignore[arg-type]


class TwimgEngine:
    engine_id = "twimg"
    capabilities = EngineCapabilities(download=True)

    def __init__(
        self,
        script_path: Path | None = None,
        process_runner: ProcessRunner = _spawn,
    ):
        self.script_path = script_path or (
            Path(__file__).resolve().parents[2]
            / "vendor"
            / "twimg"
            / "download_twitter_media.py"
        )
        self._process_runner = process_runner

    async def resolve_download(self, request: DownloadRequest) -> DownloadPlan:
        # Twimg's legacy tool resolves and transfers media in one operation;
        # this plan is descriptive while callers use run_vendor for transfer.
        return DownloadPlan(
            media_url=request.url,
            source_url=f"{urlsplit(request.url).scheme}://{urlsplit(request.url).hostname}/",
            source_page=f"{urlsplit(request.url).scheme}://{urlsplit(request.url).hostname}/",
            media_kind="external",
            suggested_name=suggested_filename(request.url),
            size=None,
        )

    async def run_vendor(
        self,
        request: DownloadRequest,
        output_dir: Path,
        *,
        cancel: asyncio.Event | None = None,
    ) -> tuple[Path, ...]:
        if not self.script_path.is_file():
            raise EngineError(ErrorCode.DEPENDENCY_MISSING, "Twimg vendor tool is missing")
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".twimg-work-", dir=output_dir) as temporary:
            staging_dir = Path(temporary)
            command = [sys.executable, str(self.script_path), request.url, "-o", temporary]
            if request.options.get("force"):
                command.append("--force")
            if request.options.get("verbose"):
                command.append("--verbose")
            for option, flag in (("parallel", "-p"), ("seg_workers", "-w"), ("quality", "-q")):
                value = request.options.get(option)
                if value is not None:
                    command.extend((flag, str(value)))
            local_addr = request.options.get("local_addr")
            if isinstance(local_addr, str) and local_addr:
                command.extend(("--local-addr", local_addr))
            try:
                process = cast(
                    ManagedProcess,
                    await self._process_runner(
                        *command,
                        cwd=temporary,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    ),
                )
            except FileNotFoundError as exc:
                raise EngineError(ErrorCode.DEPENDENCY_MISSING, "Python runtime is missing") from exc

            communicate = asyncio.create_task(process.communicate())
            cancel_wait = asyncio.create_task(cancel.wait()) if cancel else None
            try:
                if cancel_wait is None:
                    await communicate
                else:
                    done, _ = await asyncio.wait(
                        {communicate, cancel_wait}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if cancel_wait in done and cancel and cancel.is_set():
                        process.terminate()
                        await process.wait()
                        communicate.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await communicate
                        raise asyncio.CancelledError
            except asyncio.CancelledError:
                if process.returncode is None:
                    process.terminate()
                    await process.wait()
                communicate.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await communicate
                raise
            finally:
                if cancel_wait is not None:
                    cancel_wait.cancel()

            if process.returncode != 0:
                raise EngineError(ErrorCode.DOWNLOAD_FAILED, "Twimg download failed")
            staged_files = sorted(
                path
                for path in staging_dir.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and path.resolve().is_relative_to(staging_dir.resolve())
                and path.suffix.lower() in _MEDIA_SUFFIXES
            )
            if not staged_files:
                raise EngineError(ErrorCode.DOWNLOAD_FAILED, "Twimg produced no media files")
            published: list[Path] = []
            allocator = OutputAllocator()
            for source in staged_files:
                relative = source.relative_to(staging_dir)
                # Use the shared atomic reservation strategy for every vendor output.
                # Nested paths and case-only collisions must not overwrite files.
                item = DownloadPlan(
                    media_url=request.url,
                    source_url=f"{request.url}#{relative.as_posix()}",
                    source_page=request.url,
                    media_kind="external",
                    suggested_name=source.name,
                    size=source.stat().st_size,
                )
                target = allocator.reserve(item, output_dir)
                try:
                    shutil.move(str(source), target)
                except OSError as exc:
                    target.unlink(missing_ok=True)
                    raise EngineError(ErrorCode.DOWNLOAD_FAILED, "Twimg output could not be published") from exc
                published.append(target)
            return tuple(published)

    async def crawl(self, request: CrawlRequest) -> CrawlResult:
        raise EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, "Twimg does not support crawling")

    async def ranking(self, request: CrawlRequest) -> CrawlResult:
        raise EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, "Twimg does not support ranking")
