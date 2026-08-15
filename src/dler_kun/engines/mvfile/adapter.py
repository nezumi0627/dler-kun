from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ...engine import IDownloader
from ...models import (
    CacheStatus,
    CrawlItem,
    CrawlRequest,
    CrawlResult,
    DownloadRequest,
    DownloadResult,
    EngineCapability,
    JobStatus,
)
from .api import (
    DEFAULT_API_BASE,
    MvfileApiError,
    MvfileEntry,
    extract_short_link,
    fetch_info,
    list_entries,
    page_domain_from_url,
    resolve_download_targets,
)
from .hls import MvfileDownloadError, download_hls_to_mp4, target_mp4_path


class MvfileEngine(IDownloader):
    engine_id = "mvfile"
    display_name = "mvfile Engine"
    capabilities = EngineCapability(download=True, crawl=True, ranking=False)

    def detect(self, url: str) -> bool:
        host = (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower()
        supported = (
            "mvfile.com",
            "file-photo.com",
            "tweetfile.com",
            "gofile.website",
            "image-share.cc",
            "tweetplay.com",
            "imagedist.com",
            "gofile.rocks",
        )
        if any(host == domain or host.endswith(f".{domain}") for domain in supported):
            return True
        return extract_short_link(url) is not None and "mvfile" in url.lower()

    def download(self, request: DownloadRequest) -> DownloadResult:
        try:
            api_base = str(request.options.get("api_base") or DEFAULT_API_BASE)
            timeout_seconds = float(request.options.get("timeout_seconds", 30.0))
            force = bool(request.options.get("force", False))
            hls_workers = int(request.options.get("hls_workers", 8))
            local_addr = str(request.options.get("local_addr") or "")
            proxy = str(request.options.get("proxy") or "")
            password = request.options.get("password")
            targets = resolve_download_targets(
                request.url,
                api_base=api_base,
                timeout_seconds=timeout_seconds,
                password=str(password) if password else None,
                related=bool(request.options.get("related", True)),
            )
            if not targets:
                return DownloadResult(
                    job_id=request.job_id,
                    engine_id=self.engine_id,
                    status=JobStatus.FAILED,
                    message="mvfile media not found.",
                    errors=["not_found"],
                )
            output_dir = Path(request.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            cache = request.options.get("cache_manager")
            files: list[str] = []
            errors: list[str] = []
            failed: list[dict[str, str]] = []
            skipped_failed = 0
            progress = request.options.get("progress_callback")
            total = len(targets)
            for index, entry in enumerate(targets, start=1):
                cache_key = f"mvfile:{entry.short_link}"
                if cache and not force and _is_failed(cache, cache_key):
                    skipped_failed += 1
                    continue
                if callable(progress):
                    progress(
                        {
                            "phase": "download",
                            "current_file": entry.name,
                            "completed_files": index - 1 - skipped_failed,
                            "total_files": total,
                            "progress": round(((index - 1) / total) * 100, 2),
                        }
                    )
                try:
                    path = self._download_entry(
                        entry,
                        output_dir,
                        force=force,
                        timeout_seconds=timeout_seconds,
                        referer=entry.page_url,
                        hls_workers=hls_workers,
                        local_addr=local_addr,
                        proxy=proxy,
                    )
                    files.append(str(path))
                    if cache:
                        cache.mark(
                            cache_key,
                            entry.media_url or request.url,
                            path,
                            CacheStatus.COMPLETE,
                            self.engine_id,
                        )
                except MvfileDownloadError as exc:
                    message = str(exc)
                    if message.startswith("dependency_missing"):
                        return DownloadResult(
                            job_id=request.job_id,
                            engine_id=self.engine_id,
                            status=JobStatus.FAILED,
                            message=message,
                            errors=["dependency_missing"],
                            files=files,
                        )
                    errors.append("download_failed")
                    if cache:
                        cache.mark(
                            cache_key,
                            entry.media_url or request.url,
                            Path(),
                            CacheStatus.FAILED,
                            self.engine_id,
                        )
                    failed.append(
                        {
                            "name": entry.name,
                            "short_link": entry.short_link,
                            "error": message,
                        }
                    )
                except OSError as exc:
                    errors.append(str(exc))
                    if cache:
                        cache.mark(
                            cache_key,
                            entry.media_url or request.url,
                            Path(),
                            CacheStatus.FAILED,
                            self.engine_id,
                        )
                    failed.append(
                        {
                            "name": entry.name,
                            "short_link": entry.short_link,
                            "error": str(exc),
                        }
                    )
            if callable(progress):
                progress(
                    {
                        "phase": "download",
                        "completed_files": len(files),
                        "total_files": total,
                        "progress": 100 if not errors else round((len(files) / total) * 100, 2),
                    }
                )
            status = JobStatus.SUCCESS if files and not errors else JobStatus.FAILED
            if files and errors:
                status = JobStatus.FAILED
            note = f" ({skipped_failed} skipped as failed)" if skipped_failed else ""
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=status,
                message=(
                    f"mvfile download completed: {len(files)}/{total} file(s).{note}"
                    if files
                    else "mvfile download failed."
                ),
                files=files,
                errors=(["download_failed"] if errors else []),
                metadata={
                    "failed": failed[:20],
                    "skipped_failed": skipped_failed,
                    "items": [
                        {
                            "short_link": item.short_link,
                            "name": item.name,
                            "page_url": item.page_url,
                            "media_url": item.media_url,
                        }
                        for item in targets
                    ],
                },
            )
        except MvfileApiError as exc:
            return self._api_error_result(request.job_id, str(exc))
        except Exception as exc:  # noqa: BLE001 - adapter normalizes failures.
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=str(exc),
                errors=["download_failed"],
            )

    def crawl(self, request: CrawlRequest) -> CrawlResult:
        try:
            seeds = [str(seed) for seed in (request.seeds or []) if str(seed).strip()]
            if not seeds and request.options.get("seed"):
                seeds = [str(request.options["seed"])]
            if not seeds:
                return CrawlResult(
                    job_id=request.job_id,
                    engine_id=self.engine_id,
                    status=JobStatus.FAILED,
                    message="mvfile crawl requires a seed URL.",
                    errors=["invalid_request"],
                )
            api_base = str(request.options.get("api_base") or DEFAULT_API_BASE)
            timeout_seconds = float(request.options.get("timeout_seconds", 30.0))
            items: list[CrawlItem] = []
            media_entries: list[MvfileEntry] = []
            for seed in seeds:
                short_link = extract_short_link(seed)
                if not short_link:
                    continue
                domain = page_domain_from_url(seed)
                root = fetch_info(
                    short_link,
                    domain=domain,
                    api_base=api_base,
                    timeout_seconds=timeout_seconds,
                )
                if root.is_folder:
                    listed = list_entries(
                        root.short_link,
                        domain=domain,
                        api_base=api_base,
                        timeout_seconds=timeout_seconds,
                    )
                    for entry in listed:
                        items.append(self._to_crawl_item(entry))
                        if request.download and not entry.is_folder:
                            media_entries.append(
                                fetch_info(
                                    entry.short_link,
                                    domain=domain,
                                    api_base=api_base,
                                    timeout_seconds=timeout_seconds,
                                )
                            )
                else:
                    items.append(self._to_crawl_item(root))
                    if request.download:
                        media_entries.append(root)

            files: list[str] = []
            errors: list[str] = []
            if request.download and media_entries:
                output_dir = Path(request.output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                force = bool(request.options.get("force") or request.options.get("overwrite"))
                for entry in media_entries:
                    try:
                        path = self._download_entry(
                            entry,
                            output_dir,
                            force=force,
                            timeout_seconds=timeout_seconds,
                            referer=entry.page_url,
                            hls_workers=int(request.options.get("hls_workers", 8)),
                            local_addr=str(request.options.get("local_addr") or ""),
                            proxy=str(request.options.get("proxy") or ""),
                        )
                        files.append(str(path))
                    except MvfileDownloadError as exc:
                        if str(exc).startswith("dependency_missing"):
                            return CrawlResult(
                                job_id=request.job_id,
                                engine_id=self.engine_id,
                                status=JobStatus.FAILED,
                                message=str(exc),
                                items=items,
                                files=files,
                                errors=["dependency_missing"],
                            )
                        errors.append(str(exc))
            status = JobStatus.SUCCESS
            if request.download and media_entries and len(files) < len(media_entries):
                status = JobStatus.FAILED
                if "download_failed" not in errors:
                    errors.append("download_failed")
            return CrawlResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=status,
                message=f"mvfile crawl completed: {len(items)} item(s).",
                items=items,
                files=files,
                errors=errors if status == JobStatus.FAILED else [],
                metadata={"download": request.download},
            )
        except MvfileApiError as exc:
            code = str(exc)
            mapped = code if code in {
                "auth_required",
                "not_found",
                "invalid_request",
                "network_error",
            } or code.startswith("network_error") else "crawl_failed"
            if mapped.startswith("network_error"):
                mapped = "network_error"
            return CrawlResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=str(exc),
                errors=[mapped],
            )
        except Exception as exc:  # noqa: BLE001
            return CrawlResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=str(exc),
                errors=["crawl_failed"],
            )

    def _download_entry(
        self,
        entry: MvfileEntry,
        output_dir: Path,
        *,
        force: bool,
        timeout_seconds: float,
        referer: str,
        hls_workers: int = 8,
        local_addr: str = "",
        proxy: str = "",
    ) -> Path:
        if not entry.media_url:
            raise MvfileDownloadError("media url missing")
        target = target_mp4_path(output_dir, entry.name)
        return download_hls_to_mp4(
            entry.media_url,
            target,
            referer=referer,
            force=force,
            timeout_seconds=timeout_seconds,
            hls_workers=hls_workers,
            local_addr=local_addr,
            proxy=proxy,
        )

    @staticmethod
    def _to_crawl_item(entry: MvfileEntry) -> CrawlItem:
        return CrawlItem(
            url=entry.page_url,
            title=entry.name,
            published_at=None,
            thumbnail_url=entry.thumbnail_url,
            size=entry.file_size,
            duration=entry.duration,
            downloadable=not entry.is_folder,
            metadata={
                "short_link": entry.short_link,
                "is_folder": entry.is_folder,
                "media_url": entry.media_url,
                "channel_link": entry.channel_link,
            },
        )

    def _api_error_result(self, job_id: str, code: str) -> DownloadResult:
        mapped = code
        if code.startswith("network_error"):
            mapped = "network_error"
        if mapped not in {
            "unsupported_service",
            "invalid_request",
            "not_found",
            "auth_required",
            "network_error",
            "download_failed",
            "dependency_missing",
        }:
            mapped = "download_failed"
        return DownloadResult(
            job_id=job_id,
            engine_id=self.engine_id,
            status=JobStatus.FAILED,
            message=code,
            errors=[mapped],
        )


def _is_failed(cache: Any, key: str) -> bool:
    item = cache.get(key)
    return bool(item and item.get("status") == CacheStatus.FAILED.value)
