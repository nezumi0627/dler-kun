from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from ...engine import IDownloader
from ...models import (
    CrawlRequest,
    CrawlResult,
    DownloadRequest,
    DownloadResult,
    EngineCapability,
    JobStatus,
)


class GoFileEngine(IDownloader):
    engine_id = "gofile"
    display_name = "GoFile Engine"
    capabilities = EngineCapability(download=True, crawl=True, ranking=True)

    def __init__(self, project_path: str | Path, proxy: str = "") -> None:
        self.project_path = Path(project_path)
        self.proxy = proxy or None

    def detect(self, url: str) -> bool:
        return "gofile.io" in url.lower()

    def download(self, request: DownloadRequest) -> DownloadResult:
        try:
            return asyncio.run(self._download_async(request))
        except ModuleNotFoundError as exc:
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=f"GoFile dependency missing: {exc.name}",
                errors=["dependency_missing"],
            )
        except Exception as exc:  # noqa: BLE001 - adapter normalizes engine failures.
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=str(exc),
                errors=["download_failed"],
            )

    async def _download_async(self, request: DownloadRequest) -> DownloadResult:
        self._ensure_path()
        import aiohttp
        from gofile_dl.downloader import GoFileDownloader

        timeout = aiohttp.ClientTimeout(total=None)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            downloader = GoFileDownloader(session, proxy=self.proxy)
            await downloader.init()
            result = await downloader.download(
                request.url,
                password=request.options.get("password"),
                output_dir=str(request.output_dir),
            )

        status = result.get("status")
        if status == "success":
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.SUCCESS,
                message=result.get("message") or "GoFile download completed.",
                files=[str(path) for path in result.get("files", [])],
                errors=[str(error) for error in result.get("errors", [])],
                metadata=result,
            )
        return DownloadResult(
            job_id=request.job_id,
            engine_id=self.engine_id,
            status=JobStatus.FAILED,
            message=result.get("message") or "GoFile download failed.",
            errors=[str(error) for error in result.get("errors", [])] or [str(status)],
            metadata=result,
        )

    def crawl(self, request: CrawlRequest) -> CrawlResult:
        return self.ranking(request)

    def ranking(self, request: CrawlRequest) -> CrawlResult:
        ranking_script = self.project_path / "ranking_dl.py"
        if not ranking_script.exists():
            return CrawlResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=f"GoFile ranking script not found: {ranking_script}",
                errors=["dependency_missing"],
            )
        return CrawlResult(
            job_id=request.job_id,
            engine_id=self.engine_id,
            status=JobStatus.UNSUPPORTED,
            message=(
                "GoFile ranking exists as an interactive existing script. "
                "Run it directly or wire a subprocess job when needed."
            ),
            metadata={"script": str(ranking_script)},
        )

    def _ensure_path(self) -> None:
        project = str(self.project_path)
        if project not in sys.path:
            sys.path.insert(0, project)
