from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ...engine import IDownloader
from ...models import (
    CrawlItem,
    CrawlRequest,
    CrawlResult,
    DownloadRequest,
    DownloadResult,
    EngineCapability,
    JobStatus,
)


class Xo85Engine(IDownloader):
    engine_id = "85xo"
    display_name = "85xo Engine"
    capabilities = EngineCapability(download=True, crawl=True, ranking=False)

    def __init__(self, project_path: str | Path | None = None) -> None:
        self.project_path = (
            Path(project_path)
            if project_path
            else Path(__file__).resolve().parents[2] / "vendor" / "xo85"
        )
        self.lib_path = self.project_path

    def detect(self, url: str) -> bool:
        return "85xo.com" in url.lower()

    def download(self, request: DownloadRequest) -> DownloadResult:
        crawl_request = CrawlRequest(
            service=self.engine_id,
            output_dir=request.output_dir,
            job_id=request.job_id,
            seeds=[request.url],
            days=int(request.options.get("days", 10)),
            download=True,
            options=request.options,
        )
        result = self.crawl(crawl_request)
        return DownloadResult(
            job_id=request.job_id,
            engine_id=self.engine_id,
            status=result.status,
            message=result.message,
            files=result.files,
            errors=result.errors,
            metadata={
                "items": [item.__dict__ for item in result.items],
                **result.metadata,
            },
        )

    def crawl(self, request: CrawlRequest) -> CrawlResult:
        try:
            self._ensure_path()
            if request.options.get("method", "fast") != "legacy":
                return self._crawl_fast(request)
            from xo_dler import CrawlConfig, DownloadConfig, crawl_once, download_items

            seeds = request.seeds or [
                request.options.get("seed") or "https://www.85xo.com/latest-updates/"
            ]
            crawl_config = CrawlConfig(
                seeds=[str(seed) for seed in seeds],
                days=request.days,
                max_pages=int(request.options.get("max_pages", 50)),
                max_depth=int(request.options.get("max_depth", 2)),
                delay_seconds=float(request.options.get("delay_seconds", 1.0)),
                include_undated=bool(request.options.get("include_undated", False)),
                network_capture_seconds=float(
                    request.options.get("network_capture_seconds", 15.0)
                ),
                browser_path=request.options.get("browser_path"),
            )
            media_items = crawl_once(crawl_config)
            crawl_items = [self._to_crawl_item(item) for item in media_items]
            files: list[str] = []
            if request.download and media_items:
                download_config = DownloadConfig(
                    output_dir=request.output_dir,
                    skip_existing=not bool(request.options.get("overwrite", False)),
                )
                files = [
                    str(path) for path in download_items(media_items, download_config)
                ]
            return CrawlResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.SUCCESS,
                message=f"85xo crawl completed: {len(crawl_items)} item(s).",
                items=crawl_items,
                files=files,
                metadata={"download": request.download},
            )
        except ModuleNotFoundError as exc:
            return CrawlResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=f"85xo dependency missing: {exc.name}",
                errors=["dependency_missing"],
            )
        except Exception as exc:  # noqa: BLE001 - adapter normalizes engine failures.
            return CrawlResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=str(exc),
                errors=["crawl_failed"],
            )

    def _crawl_fast(self, request: CrawlRequest) -> CrawlResult:
        from xo_dler import DownloadConfig

        from .fast import (
            crawl_fast,
            download_existing_items_parallel,
            to_existing_media_items,
        )

        seeds = request.seeds or [
            request.options.get("seed") or "https://www.85xo.com/latest-updates/"
        ]
        fast_items = crawl_fast(
            seeds=[str(seed) for seed in seeds],
            days=request.days,
            max_pages=int(request.options.get("max_pages", 50)),
            timeout_seconds=float(request.options.get("timeout_seconds", 30.0)),
            resolve_workers=int(request.options.get("resolve_workers", 6)),
        )
        media_items = to_existing_media_items(fast_items, self.project_path)
        crawl_items = [self._to_crawl_item(item) for item in media_items]
        files: list[str] = []
        if request.download and media_items:
            download_config = DownloadConfig(
                output_dir=request.output_dir,
                skip_existing=not bool(request.options.get("overwrite", False)),
            )
            files = [
                str(path)
                for path in download_existing_items_parallel(
                    media_items,
                    download_config,
                    max_workers=int(request.options.get("parallel_downloads", 4)),
                    read_timeout_seconds=float(
                        request.options.get("download_read_timeout", 30.0)
                    ),
                    attempts=int(request.options.get("download_attempts", 2)),
                    cache_path=Path(
                        str(request.options.get("cache_path", "download_cache.json"))
                    ),
                    progress_callback=request.options.get("progress_callback"),
                )
            ]
        return CrawlResult(
            job_id=request.job_id,
            engine_id=self.engine_id,
            status=JobStatus.SUCCESS,
            message=f"85xo fast crawl completed: {len(crawl_items)} item(s).",
            items=crawl_items,
            files=files,
            metadata={"download": request.download, "method": "fast"},
        )

    def _ensure_path(self) -> None:
        lib = str(self.lib_path)
        if lib not in sys.path:
            sys.path.insert(0, lib)

    @staticmethod
    def _to_crawl_item(item: Any) -> CrawlItem:
        published_at = getattr(item, "published_at", None)
        if published_at is not None and hasattr(published_at, "isoformat"):
            published_at = published_at.isoformat()
        return CrawlItem(
            url=str(getattr(item, "url", "")),
            title=str(getattr(item, "title", "") or getattr(item, "filename", "")),
            published_at=published_at,
            downloadable=True,
            metadata={
                "source_page": getattr(item, "source_page", ""),
                "display_name": getattr(item, "display_name", ""),
            },
        )
