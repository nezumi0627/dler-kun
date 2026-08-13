from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from ...engine import IDownloader
from .seeds import resolve_85xo_seeds
from ...models import (
    CrawlItem,
    CrawlRequest,
    CrawlResult,
    DownloadRequest,
    DownloadResult,
    EngineCapability,
    JobStatus,
)


class Engine85xo(IDownloader):
    engine_id = "85xo"
    display_name = "85xo Engine"
    capabilities = EngineCapability(download=True, crawl=True, ranking=False)

    def __init__(self, project_path: str | Path | None = None) -> None:
        self.project_path = (
            Path(project_path)
            if project_path
            else Path(__file__).resolve().parents[2] / "vendor" / "85xo"
        )
        self.lib_path = self.project_path

    def detect(self, url: str) -> bool:
        lowered = url.lower()
        return any(d in lowered for d in ("85xo.com", "85po.net", "85po.com"))

    def download(self, request: DownloadRequest) -> DownloadResult:
        if self._is_direct_media_url(request.url) or self._is_video_page_url(
            request.url
        ):
            return self._download_direct(request)
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

            user_agent = str(request.options.get("user_agent") or "")
            seeds = resolve_85xo_seeds(
                request.seeds,
                option_seed=request.options.get("seed"),
                sources=request.options.get("sources"),
            )
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
            if user_agent:
                crawl_config = replace(crawl_config, user_agent=user_agent)
            media_items = crawl_once(crawl_config)
            crawl_items = [self._to_crawl_item(item) for item in media_items]
            files: list[str] = []
            status = JobStatus.SUCCESS
            errors: list[str] = []
            if request.download and media_items:
                download_config = DownloadConfig(
                    output_dir=request.output_dir,
                    skip_existing=not bool(request.options.get("overwrite", False)),
                )
                if user_agent:
                    download_config = replace(download_config, user_agent=user_agent)
                files = [
                    str(path) for path in download_items(media_items, download_config)
                ]
                if len(files) < len(media_items):
                    status = JobStatus.FAILED
                    errors.append("download_failed")
            return CrawlResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=status,
                message=f"85xo crawl completed: {len(crawl_items)} item(s).",
                items=crawl_items,
                files=files,
                errors=errors,
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
        self._ensure_path()
        from xo_dler import DownloadConfig

        from .fast import (
            crawl_fast,
            download_existing_items_parallel,
            to_existing_media_items,
        )

        user_agent = str(request.options.get("user_agent") or "")
        stop_event = request.options.get("stop_event")
        resolve_cache = request.options.get("resolve_cache")
        seeds = resolve_85xo_seeds(
            request.seeds,
            option_seed=request.options.get("seed"),
            sources=request.options.get("sources"),
        )
        fast_items = crawl_fast(
            seeds=[str(seed) for seed in seeds],
            days=request.days,
            max_pages=int(request.options.get("max_pages", 50)),
            timeout_seconds=float(request.options.get("timeout_seconds", 30.0)),
            resolve_workers=int(request.options.get("resolve_workers", 6)),
            include_undated=bool(request.options.get("include_undated", False)),
            discover_workers=int(request.options.get("discover_workers", 6)),
            stop_event=stop_event,
            resolve_cache=resolve_cache,
        )
        media_items = to_existing_media_items(fast_items, self.project_path)
        crawl_items = [self._to_crawl_item(item) for item in media_items]
        files: list[str] = []
        status = JobStatus.SUCCESS
        errors: list[str] = []
        if request.download and media_items:
            download_config = DownloadConfig(
                output_dir=request.output_dir,
                skip_existing=not bool(request.options.get("overwrite", False)),
            )
            if user_agent:
                download_config = replace(download_config, user_agent=user_agent)
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
                    max_time_seconds=_optional_positive_float(
                        request.options.get("download_max_time")
                    ),
                    cache_manager=request.options.get("cache_manager"),
                    progress_callback=request.options.get("progress_callback"),
                    write_metadata_sidecar=bool(request.options.get("metadata", False)),
                    stop_event=stop_event,
                )
            ]
            if len(files) < len(media_items):
                status = JobStatus.FAILED
                errors.append("download_failed")
        return CrawlResult(
            job_id=request.job_id,
            engine_id=self.engine_id,
            status=status,
            message=f"85xo fast crawl completed: {len(crawl_items)} item(s).",
            items=crawl_items,
            files=files,
            errors=errors,
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

    def _download_direct(self, request: DownloadRequest) -> DownloadResult:
        try:
            self._ensure_path()
            from xo_dler import DownloadConfig

            from .fast import (
                direct_media_items_from_url,
                download_existing_items_parallel,
                to_existing_media_items,
            )

            user_agent = str(request.options.get("user_agent") or "")
            stop_event = request.options.get("stop_event")
            fast_items = direct_media_items_from_url(
                request.url,
                timeout_seconds=float(request.options.get("timeout_seconds", 30.0)),
            )
            media_items = to_existing_media_items(fast_items, self.project_path)
            if not media_items:
                return DownloadResult(
                    job_id=request.job_id,
                    engine_id=self.engine_id,
                    status=JobStatus.FAILED,
                    message="85xo media url not found.",
                    errors=["not_found"],
                )
            download_config = DownloadConfig(
                output_dir=request.output_dir,
                skip_existing=not bool(request.options.get("force", False)),
            )
            if user_agent:
                download_config = replace(download_config, user_agent=user_agent)
            files = [
                str(path)
                for path in download_existing_items_parallel(
                    media_items,
                    download_config,
                    max_workers=int(request.options.get("parallel_downloads", 1)),
                    read_timeout_seconds=float(
                        request.options.get("download_read_timeout", 30.0)
                    ),
                    attempts=int(request.options.get("download_attempts", 2)),
                    max_time_seconds=_optional_positive_float(
                        request.options.get("download_max_time")
                    ),
                    cache_manager=request.options.get("cache_manager"),
                    progress_callback=request.options.get("progress_callback"),
                    write_metadata_sidecar=bool(request.options.get("metadata", False)),
                    stop_event=stop_event,
                )
            ]
            status = (
                JobStatus.SUCCESS
                if len(files) == len(media_items)
                else JobStatus.FAILED
            )
            errors = [] if status == JobStatus.SUCCESS else ["download_failed"]
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=status,
                message=f"85xo direct download completed: {len(files)}/{len(media_items)} file(s).",
                files=files,
                errors=errors,
                metadata={
                    "direct": True,
                    "items": [
                        {
                            "url": item.url,
                            "source_page": item.source_page,
                            "title": item.title,
                            "published_at": (
                                item.published_at.isoformat()
                                if item.published_at is not None
                                else None
                            ),
                        }
                        for item in fast_items
                    ],
                },
            )
        except ModuleNotFoundError as exc:
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=f"85xo dependency missing: {exc.name}",
                errors=["dependency_missing"],
            )
        except Exception as exc:  # noqa: BLE001
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=str(exc),
                errors=["download_failed"],
            )

    @staticmethod
    def _is_video_page_url(url: str) -> bool:
        return "/v/" in url.lower()

    @staticmethod
    def _is_direct_media_url(url: str) -> bool:
        lowered = url.lower()
        return "/get_file/" in lowered and ".mp4" in lowered


def _optional_positive_float(value: Any) -> float | None:
    if value in (None, "", False):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
