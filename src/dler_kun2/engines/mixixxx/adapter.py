"""Browser-bound mixi-xxx downloader with async discovery and partial crawl results."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from dler_kun2.domain.contracts import CrawlRequest, DownloadRequest, EngineCapabilities
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import CrawlResult
from dler_kun2.domain.plans import DownloadPlan
from dler_kun2.infrastructure.storage.paths import OutputAllocator

from .browser import BrowserCaptureError, BrowserHlsDownloader
from .embed_parser import extract_embed_url
from .listing_parser import VideoPage, listing_page_url, parse_listing

_HOSTS = {"mixi-xxx.cc", "www.mixi-xxx.cc", "jav-mixi.cc", "www.jav-mixi.cc"}


class TextResponse(Protocol):
    async def text(self) -> str: ...


class HttpClient(Protocol):
    async def request(self, method: str, url: str, **kwargs) -> TextResponse: ...


class MixixxxEngine:
    engine_id = "mixixxx"
    capabilities = EngineCapabilities(download=True, crawl=True)

    def __init__(self, http: HttpClient, *, browser_path: str | None = None, ffmpeg_path: str | None = None):
        self.http = http
        self.browser_path = browser_path
        self.ffmpeg_path = ffmpeg_path

    @staticmethod
    def _canonical(url: str) -> str:
        try:
            parsed = urlsplit(url)
            parsed.port
        except ValueError as exc:
            raise EngineError(ErrorCode.INVALID_REQUEST, "invalid mixi-xxx URL") from exc
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in _HOSTS or parsed.username or parsed.password:
            raise EngineError(ErrorCode.INVALID_REQUEST, "unsupported mixi-xxx URL")
        if parsed.hostname in {"mixi-xxx.cc", "www.mixi-xxx.cc"}:
            return urlunsplit(("https", "jav-mixi.cc", parsed.path, parsed.query, ""))
        return urlunsplit(("https", parsed.netloc.lower(), parsed.path, parsed.query, ""))

    async def _text(self, url: str) -> str:
        from dler_kun2.infrastructure.http.client import HttpError

        try:
            response = await self.http.request("GET", url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
            return await response.text()
        except HttpError as exc:
            raise EngineError(exc.code, "mixi-xxx page request failed", exc.retry_after) from exc

    async def _resolve_page(self, url: str, title: str = "") -> DownloadPlan:
        page_url = self._canonical(url)
        html = await self._text(page_url)
        embed = extract_embed_url(html)
        if not embed:
            raise EngineError(ErrorCode.NOT_FOUND, "video page has no supported player")
        name = " ".join(title.split()) or Path(urlsplit(page_url).path.rstrip("/")).name or "video"
        return DownloadPlan(embed, page_url, page_url, "browser_hls", f"{name}.mp4", None)

    async def resolve_download(self, request: DownloadRequest) -> DownloadPlan:
        return await self._resolve_page(request.url)

    async def download_plan(self, plan: DownloadPlan, output_dir: Path, *, segment_concurrency: int = 4, browser_path: str | None = None, ffmpeg_path: str | None = None, timeout: float = 60) -> Path:
        output = OutputAllocator().reserve(plan, output_dir)
        descriptor, staging_name = tempfile.mkstemp(prefix=".mixi-stage-", suffix=".mp4", dir=output.parent)
        os.close(descriptor)
        staging = Path(staging_name)
        staging.unlink(missing_ok=True)
        try:
            browser = BrowserHlsDownloader(
                browser_path=browser_path or self.browser_path,
                ffmpeg_path=ffmpeg_path or self.ffmpeg_path,
                timeout=timeout,
            )
            await asyncio.to_thread(browser.download, plan.media_url, staging, concurrency=segment_concurrency)
            os.replace(staging, output)
            return output
        except BrowserCaptureError as exc:
            output.unlink(missing_ok=True)
            code = ErrorCode.DEPENDENCY_MISSING if "required" in str(exc) else ErrorCode.DOWNLOAD_FAILED
            raise EngineError(code, str(exc)) from exc
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        finally:
            staging.unlink(missing_ok=True)

    async def run_vendor(self, request: DownloadRequest, output_dir: Path, *, cancel=None) -> tuple[Path, ...]:
        if cancel is not None and cancel.is_set():
            raise asyncio.CancelledError
        plan = await self.resolve_download(request)
        path = await self.download_plan(
            plan,
            output_dir,
            segment_concurrency=int(request.options.get("segment_concurrency", 4)),
            browser_path=str(request.options.get("browser_path") or "") or None,
            ffmpeg_path=str(request.options.get("ffmpeg_path") or "") or None,
            timeout=float(request.options.get("timeout_seconds", 60.0)),
        )
        return (path,)

    async def crawl(self, request: CrawlRequest) -> CrawlResult:
        max_pages = int(request.options.get("max_pages", 5))
        limit = int(request.options.get("limit", 0))
        workers = int(request.options.get("resolve_workers", 4))
        if not 1 <= max_pages <= 100 or limit < 0 or not 1 <= workers <= 12:
            raise EngineError(ErrorCode.INVALID_REQUEST, "mixi-xxx crawl limits are outside supported bounds")
        seeds = request.seeds or ("https://jav-mixi.cc/",)
        pages: list[VideoPage] = []
        errors: list[EngineError] = []
        seen: set[str] = set()
        for seed in seeds:
            canonical = self._canonical(seed)
            for page_number in range(1, max_pages + 1):
                page_url = listing_page_url(canonical, page_number)
                try:
                    items = parse_listing(await self._text(page_url), page_url)
                except EngineError as exc:
                    errors.append(exc)
                    continue
                if not items:
                    break
                for item in items:
                    if item.url not in seen:
                        seen.add(item.url)
                        pages.append(item)
                if limit and len(pages) >= limit:
                    pages = pages[:limit]
                    break
        semaphore = asyncio.Semaphore(workers)

        async def resolve(item: VideoPage):
            async with semaphore:
                try:
                    return await self._resolve_page(item.url, item.title)
                except EngineError as exc:
                    return exc

        values = await asyncio.gather(*(resolve(item) for item in pages))
        plans = tuple(value for value in values if isinstance(value, DownloadPlan))
        errors.extend(value for value in values if isinstance(value, EngineError))
        return CrawlResult(plans=plans, requested=len(seeds), discovered=len(pages), unavailable=len(pages) - len(plans), errors=tuple(errors))

    async def ranking(self, request: CrawlRequest) -> CrawlResult:
        raise EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, "mixi-xxx has no ranking operation")
