from __future__ import annotations

import asyncio
import io
import re
from collections.abc import Iterator
from contextlib import contextmanager
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
    _DOUGA_SEEDS,
    DEFAULT_GOFILE_RANKING_SEEDS,
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

_GOFILE_ID_RE = re.compile(r"gofile\.io/d/([A-Za-z0-9]+)", re.I)


class GoFileEngine(IDownloader):
    engine_id = "gofile"
    display_name = "GoFile Engine"
    capabilities = EngineCapability(download=True, crawl=True, ranking=True)

    def __init__(self, proxy: str = "") -> None:
        self.proxy = proxy or None

    def detect(self, url: str) -> bool:
        lowered = url.lower()
        return any(
            d in lowered
            for d in ("gofile.io", "gofile-douga.com", "gofilelab.com")
        )

    def download(self, request: DownloadRequest) -> DownloadResult:
        # gofile-douga.com / gofilelab.com are listing pages (not a single file
        # page), so download the whole listing via the crawl path.
        lowered = request.url.lower()
        if "gofile-douga.com" in lowered or "gofilelab.com" in lowered:
            crawl_request = CrawlRequest(
                service=self.engine_id,
                output_dir=request.output_dir,
                job_id=request.job_id,
                seeds=[request.url],
                download=True,
                options=request.options,
            )
            result = self.ranking(crawl_request)
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
        import aiohttp

        from .gofile_dl.downloader import GoFileDownloader

        timeout = aiohttp.ClientTimeout(total=None)
        password = request.options.get("password")
        local_addr = str(request.options.get("local_addr") or "")
        proxy = str(request.options.get("proxy") or "") or self.proxy or ""
        output_dir = str(self._download_root(request))
        progress_callback = request.options.get("progress_callback")
        label = _content_label(request.url)

        if progress_callback:
            progress_callback(
                {
                    "completed_files": 0,
                    "total_files": 1,
                    "current_file": label,
                    "state": "downloading",
                }
            )

        with _suppress_gofile_rich_ui():
            async with aiohttp.ClientSession(timeout=timeout) as session:
                result = await self._download_with_session(
                    session,
                    GoFileDownloader,
                    url=request.url,
                    password=password,
                    output_dir=output_dir,
                    local_addr=local_addr,
                    proxy=proxy,
                )
                # Stale guest tokens in tokens.json often return HTTP 401.
                # Invalidate and retry once with a fresh guest account (wrapper-side).
                if _is_unauthorized_result(result):
                    fresh_token = await self._refresh_guest_token(session)
                    if fresh_token:
                        result = await self._download_with_session(
                            session,
                            GoFileDownloader,
                            url=request.url,
                            password=password,
                            output_dir=output_dir,
                            token=fresh_token,
                            local_addr=local_addr,
                            proxy=proxy,
                        )

        download_result = self._download_result_from_payload(request, result)
        if progress_callback:
            done = max(1, len(download_result.files)) if download_result.files else 0
            total = max(1, done)
            progress_callback(
                {
                    "completed_files": done
                    if download_result.status == JobStatus.SUCCESS
                    else done,
                    "total_files": total,
                    "current_file": label,
                    "progress": 100
                    if download_result.status == JobStatus.SUCCESS
                    else 0,
                    "state": download_result.status.value,
                }
            )
        return download_result

    async def _download_with_session(
        self,
        session: Any,
        downloader_cls: Any,
        *,
        url: str,
        password: Any,
        output_dir: str,
        token: str | None = None,
        local_addr: str = "",
        proxy: str = "",
    ) -> dict[str, Any]:
        downloader = downloader_cls(
            session,
            token=token,
            proxy=proxy or self.proxy,
            local_addr=local_addr or None,
        )
        await downloader.init()
        return await downloader.download(
            url,
            password=password,
            output_dir=output_dir,
        )

    async def _refresh_guest_token(self, session: Any) -> str | None:
        """Invalidate the cached guest token and mint a new one."""
        from .gofile_dl.token.token_manager import TokenManager

        manager = TokenManager()
        stale = await manager.get_valid_token()
        if stale:
            try:
                await manager.invalidate_token(stale)
            except Exception:
                pass
        try:
            return await manager.create_new_token()
        except Exception:
            # Fall back to a one-shot guest account via the content API path.
            try:
                from .gofile_dl.downloader.go_file_api import GoFileAPI

                api = GoFileAPI(session, proxy=self.proxy)
                return await api._create_guest_account()
            except Exception:
                return None

    def _download_result_from_payload(
        self,
        request: DownloadRequest,
        result: dict[str, Any],
    ) -> DownloadResult:
        status = result.get("status")
        files = _normalize_downloaded_files(result.get("files") or [])
        if status == "success":
            count = len(files)
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.SUCCESS,
                message=f"Downloaded {count} file(s).",
                files=files,
                errors=[],
                metadata=result,
            )

        message = result.get("message") or "GoFile download failed."
        errors = [str(error) for error in result.get("errors", [])]
        if not errors:
            if status == "not_found":
                errors = ["not_found"]
            elif _is_unauthorized_result(result):
                errors = ["auth_required"]
            else:
                errors = [str(status or "download_failed")]
        elif _is_unauthorized_result(result) and "auth_required" not in errors:
            errors = ["auth_required", *errors]

        return DownloadResult(
            job_id=request.job_id,
            engine_id=self.engine_id,
            status=JobStatus.FAILED,
            message=message,
            files=files,
            errors=errors,
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
        status = (
            JobStatus.FAILED
            if retryable.intersection(unique_errors)
            else JobStatus.SUCCESS
        )

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
                progress_callback(
                    {"progress": 100, "state": "downloading", "eta": f"{total}/{total}"}
                )

        message = f"GoFile ranking completed: {len(items)} item(s)."
        if request.download:
            message = (
                f"GoFile ranking download completed: {len(files)}/{len(items)} file(s)."
            )
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

    def _download_root(self, request: DownloadRequest) -> Path:
        # Per-download ID folder is applied centrally (app.download_urls).
        return request.output_dir

    def _ranking_download_root(self, request: CrawlRequest) -> Path:
        output_dir = request.output_dir
        if output_dir.name.lower() in {self.engine_id, "rankings"}:
            return output_dir
        return output_dir / self.engine_id


def _is_unauthorized_result(result: dict[str, Any]) -> bool:
    message = str(result.get("message") or "")
    lowered = message.lower()
    return "unauthorized" in lowered or "アクセス権" in message


def _content_label(url: str) -> str:
    match = _GOFILE_ID_RE.search(str(url))
    if match:
        return match.group(1)
    return str(url).strip() or "gofile"


def _normalize_downloaded_files(files: list[Any]) -> list[str]:
    paths: list[str] = []
    for item in files:
        if isinstance(item, dict):
            path = item.get("path") or item.get("filename") or ""
        else:
            path = item
        text = str(path).strip()
        if text:
            paths.append(text)
    return paths


@contextmanager
def _suppress_gofile_rich_ui() -> Iterator[None]:
    """Silence Rich panels in the integrated gofile downloader."""
    try:
        from rich.console import Console

        from .gofile_dl.downloader import file_downloader, go_file_downloader
    except Exception:
        yield
        return

    sink = io.StringIO()
    quiet = Console(file=sink, force_terminal=False, no_color=True, quiet=True)
    originals = (
        getattr(go_file_downloader, "console"),
        getattr(file_downloader, "console"),
    )
    setattr(go_file_downloader, "console", quiet)
    setattr(file_downloader, "console", quiet)
    try:
        yield
    finally:
        setattr(go_file_downloader, "console", originals[0])
        setattr(file_downloader, "console", originals[1])


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
