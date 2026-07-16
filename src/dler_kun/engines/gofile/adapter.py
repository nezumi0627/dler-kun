from __future__ import annotations

import asyncio
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
from .douga import (
    DougaFetchError,
    fetch_douga_urls,
    parse_douga_seed,
)
from .lab import LabFetchError, parse_lab_seed, scrape_lab_sources
from .seeds import (
    DEFAULT_GOFILE_RANKING_SEEDS,
    _DOUGA_SEEDS,
    classify_ranking_seed,
    resolve_gofile_ranking_seeds,
)

# Re-exported for tests and adapter-level patching.
__all__ = [
    "GoFileEngine",
    "collect_douga_urls",
    "fetch_douga_urls",
    "scrape_lab_sources",
]


class GoFileEngine(IDownloader):
    engine_id = "gofile"
    display_name = "GoFile Engine"
    capabilities = EngineCapability(download=True, crawl=True, ranking=True)

    def __init__(self, project_path: str | Path | None = None, proxy: str = "") -> None:
        self.project_path = (
            Path(project_path)
            if project_path
            else Path(__file__).resolve().parents[2] / "vendor" / "gofile"
        )
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
                output_dir=str(self._download_root(request)),
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
        try:
            return asyncio.run(self._ranking_async(request))
        except ModuleNotFoundError as exc:
            return CrawlResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=f"GoFile dependency missing: {exc.name}",
                errors=["dependency_missing"],
            )
        except Exception as exc:  # noqa: BLE001 - adapter normalizes engine failures.
            # Let app-layer cancel propagate (raised via progress_callback).
            if type(exc).__name__ == "JobCancelled":
                raise
            return CrawlResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=str(exc),
                errors=["crawl_failed"],
            )

    async def _ranking_async(self, request: CrawlRequest) -> CrawlResult:
        self._ensure_path()

        limit = max(1, int(request.options.get("limit", 60)))
        max_more_clicks = int(request.options.get("max_more_clicks", 5))
        user_agent = str(request.options.get("user_agent") or "")
        resolved_seeds = _resolve_ranking_seeds(request)
        progress_callback = request.options.get("progress_callback")

        douga_enabled, lab_enabled = _infer_source_flags(request, resolved_seeds)

        items: list[CrawlItem] = []
        seen_urls: set[str] = set()
        errors: list[str] = []
        metadata: dict[str, Any] = {
            "download": request.download,
            "seeds": resolved_seeds,
            "douga_enabled": douga_enabled,
            "lab_enabled": lab_enabled,
        }

        if douga_enabled:
            try:
                import aiohttp

                connector = aiohttp.TCPConnector()
                async with aiohttp.ClientSession(connector=connector) as session:
                    douga_urls = await collect_douga_urls(
                        session,
                        resolved_seeds,
                        limit=limit,
                    )
                for url, source in douga_urls:
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    items.append(
                        CrawlItem(
                            url=url,
                            downloadable=True,
                            metadata={"source": source},
                        )
                    )
                    if len(items) >= limit:
                        break
            except ModuleNotFoundError:
                errors.append("dependency_missing")
                metadata["douga_error"] = "aiohttp is required for gofile-douga"
            except DougaFetchError as exc:
                errors.append("network_error")
                metadata["douga_error"] = str(exc)
            except Exception as exc:  # noqa: BLE001
                errors.append("crawl_failed")
                metadata["douga_error"] = str(exc)

        if lab_enabled and len(items) < limit:
            lab_seeds = _lab_seeds_from_resolved(resolved_seeds)
            if lab_seeds is not None and len(lab_seeds) == 0:
                metadata["lab_skipped"] = "no lab seeds in resolved list"
            else:
                try:
                    lab_results = await scrape_lab_sources(
                        lab_seeds,
                        max_more_clicks=max_more_clicks,
                        user_agent=user_agent or None,
                    )
                    for source_key, urls in lab_results.items():
                        for url in urls:
                            if url in seen_urls:
                                continue
                            seen_urls.add(url)
                            items.append(
                                CrawlItem(
                                    url=url,
                                    downloadable=True,
                                    metadata={"source": f"lab:{source_key}"},
                                )
                            )
                            if len(items) >= limit:
                                break
                        if len(items) >= limit:
                            break
                except ModuleNotFoundError:
                    errors.append("dependency_missing")
                    metadata["lab_error"] = "aiohttp is required for gofilelab"
                except LabFetchError as exc:
                    errors.append("network_error")
                    metadata["lab_error"] = str(exc)
                except Exception as exc:  # noqa: BLE001
                    errors.append("crawl_failed")
                    metadata["lab_error"] = str(exc)

        items = items[:limit]
        unique_errors = sorted(set(errors))
        retryable = {"network_error", "crawl_failed", "dependency_missing"}

        if not items and unique_errors:
            return CrawlResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message="GoFile ranking crawl failed.",
                items=items,
                errors=unique_errors,
                metadata=metadata,
            )

        # Partial source failures must not look like full SUCCESS (blocks retry).
        status = JobStatus.FAILED if retryable.intersection(unique_errors) else JobStatus.SUCCESS

        files: list[str] = []
        if request.download and items:
            download_dir = self._ranking_download_root(request)
            total = len(items)
            for index, item in enumerate(items, start=1):
                if progress_callback:
                    progress_callback(
                        {
                            "progress": ((index - 1) / total) * 100,
                            "state": "downloading",
                            "eta": f"{index}/{total}",
                        }
                    )
                download_request = DownloadRequest(
                    url=item.url,
                    output_dir=download_dir,
                    job_id=request.job_id,
                    engine_id=self.engine_id,
                    options=dict(request.options),
                )
                result = await self._download_async(download_request)
                files.extend(result.files)
                if result.status != JobStatus.SUCCESS:
                    status = JobStatus.FAILED
                    if result.errors:
                        unique_errors = sorted(set(unique_errors + list(result.errors)))
                    else:
                        unique_errors = sorted(set(unique_errors + ["download_failed"]))
            if progress_callback:
                progress_callback({"progress": 100, "state": "downloading", "eta": f"{total}/{total}"})

        message = f"GoFile ranking completed: {len(items)} item(s)."
        if request.download:
            message = f"GoFile ranking download completed: {len(files)}/{len(items)} file(s)."
        if unique_errors and status == JobStatus.FAILED:
            message = f"{message} errors={','.join(unique_errors)}"

        return CrawlResult(
            job_id=request.job_id,
            engine_id=self.engine_id,
            status=status,
            message=message,
            items=items,
            files=files,
            errors=unique_errors,
            metadata=metadata,
        )

    def _ensure_path(self) -> None:
        project = str(self.project_path)
        if project not in sys.path:
            sys.path.insert(0, project)

    def _download_root(self, request: DownloadRequest) -> Path:
        output_dir = request.output_dir
        if output_dir.name.lower() == self.engine_id:
            return output_dir
        return output_dir / self.engine_id

    def _ranking_download_root(self, request: CrawlRequest) -> Path:
        output_dir = request.output_dir
        if output_dir.name.lower() in {self.engine_id, "rankings"}:
            return output_dir
        return output_dir / self.engine_id


async def collect_douga_urls(
    session: Any,
    seeds: list[str],
    *,
    limit: int = 60,
) -> list[tuple[str, str]]:
    """Fetch GoFile URLs from gofile-douga seeds; returns (url, source label) pairs.

    Global ``limit`` is shared across source keys (not per-key).
    If ``seeds`` is empty, falls back to all douga defaults.
    If ``seeds`` is non-empty but contains no douga URLs, returns [] (no fallback).
    """
    limit = max(1, int(limit))
    source_keys: set[str] = set()
    for seed in seeds:
        if classify_ranking_seed(seed) != "douga":
            continue
        key = parse_douga_seed(seed)
        if key:
            source_keys.add(key)

    if not source_keys:
        if seeds:
            return []
        for seed in _DOUGA_SEEDS:
            key = parse_douga_seed(seed)
            if key:
                source_keys.add(key)

    collected: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key in sorted(source_keys):
        if len(collected) >= limit:
            break
        remaining = limit - len(collected)
        urls = await fetch_douga_urls(session, key, limit=remaining)
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            collected.append((url, f"douga:{key}"))
            if len(collected) >= limit:
                break
    return collected


def _infer_source_flags(
    request: CrawlRequest,
    resolved_seeds: list[str],
) -> tuple[bool, bool]:
    """Prefer explicit options; otherwise infer from resolved seed hosts."""
    if "douga_enabled" in request.options or "lab_enabled" in request.options:
        return (
            bool(request.options.get("douga_enabled", True)),
            bool(request.options.get("lab_enabled", True)),
        )
    has_douga = any(classify_ranking_seed(seed) == "douga" for seed in resolved_seeds)
    has_lab = any(classify_ranking_seed(seed) == "lab" for seed in resolved_seeds)
    if has_douga and not has_lab:
        return True, False
    if has_lab and not has_douga:
        return False, True
    return True, True


def _resolve_ranking_seeds(request: CrawlRequest) -> list[str]:
    explicit = [str(seed).strip() for seed in request.seeds if str(seed).strip()]
    sources = [
        str(source).strip()
        for source in request.options.get("sources", [])
        if str(source).strip()
    ]

    resolved = resolve_gofile_ranking_seeds(
        seeds=explicit or None,
        option_seed=request.options.get("seed"),
        config_seeds=request.options.get("config_seeds"),
        sources=sources or None,
    )
    if resolved:
        return resolved
    return list(DEFAULT_GOFILE_RANKING_SEEDS)


def _lab_seeds_from_resolved(resolved_seeds: list[str]) -> list[str] | None:
    lab_seeds = [
        seed
        for seed in resolved_seeds
        if classify_ranking_seed(seed) == "lab" or parse_lab_seed(seed)
    ]
    if lab_seeds:
        return lab_seeds

    has_douga_only = bool(resolved_seeds) and all(
        classify_ranking_seed(seed) == "douga" for seed in resolved_seeds
    )
    if has_douga_only:
        return []
    return None
