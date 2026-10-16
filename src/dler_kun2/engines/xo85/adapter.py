"""85po crawler with ordered pagination, bounded media resolution, and partial errors."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlsplit

from dler_kun2.domain.contracts import CrawlRequest, DownloadRequest, EngineCapabilities
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import CrawlResult
from dler_kun2.domain.plans import DownloadPlan

from .dates import within_days
from .listing_parser import ListingItem, parse_listing
from .seeds import resolve_seeds
from .video_parser import parse_media_page

_VIDEO_ID = re.compile(r"/(?:v|video)/(\d+)(?:\.html)?(?:/|$)", re.I)
_MEDIA_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


class TextResponse(Protocol):
    async def text(self) -> str: ...


class HttpClient(Protocol):
    async def request(self, method: str, url: str, **kwargs) -> TextResponse: ...


class Xo85Engine:
    engine_id = "85xo"
    capabilities = EngineCapabilities(download=True, crawl=True)

    def __init__(self, http: HttpClient):
        self.http = http

    async def _text(self, url: str) -> str:
        try:
            response = await self.http.request("GET", url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
            return await response.text()
        except Exception as exc:
            code = getattr(exc, "code", ErrorCode.NETWORK_ERROR)
            raise EngineError(code if isinstance(code, ErrorCode) else ErrorCode.NETWORK_ERROR, "85po page request failed", getattr(exc, "retry_after", None)) from exc

    async def _resolve(self, item: ListingItem) -> DownloadPlan:
        html = await self._text(item.page_url)
        media, published = parse_media_page(html, item.page_url)
        if not media:
            raise EngineError(ErrorCode.NOT_FOUND, "video page has no direct media")
        suffix = urlsplit(media).path.lower().rsplit(".", 1)
        extension = f".{suffix[-1]}" if len(suffix) > 1 else ".mp4"
        if extension not in _MEDIA_EXTENSIONS:
            raise EngineError(ErrorCode.NOT_FOUND, "video page media type is unsupported")
        name = item.title.strip() or f"85po-{item.video_id}"
        name = name if name.lower().endswith(extension) else f"{name}{extension}"
        metadata = {"video_id": item.video_id}
        if published:
            metadata["published_at"] = published.isoformat()
        return DownloadPlan(media, item.page_url, item.page_url, extension[1:], name, None, metadata)

    async def resolve_download(self, request: DownloadRequest) -> DownloadPlan:
        parsed = urlsplit(request.url)
        if parsed.hostname not in {"85po.net", "www.85po.net"}:
            raise EngineError(ErrorCode.UNSUPPORTED_SERVICE, "unverified 85xo host")
        match = _VIDEO_ID.search(parsed.path)
        if not match:
            raise EngineError(ErrorCode.INVALID_REQUEST, "download URL must identify one video")
        item = ListingItem(request.url, match.group(1), "", None)
        return await self._resolve(item)

    async def crawl(self, request: CrawlRequest) -> CrawlResult:
        max_pages = int(request.options.get("max_pages", 50))
        days = request.days if request.days is not None else int(request.options.get("days", 10))
        limit = int(request.options.get("limit", 0))
        workers = int(request.options.get("resolve_workers", 4))
        if not 1 <= max_pages <= 500 or not 1 <= days <= 3650 or not 1 <= workers <= 16 or limit < 0:
            raise EngineError(ErrorCode.INVALID_REQUEST, "85xo crawl limits are outside supported bounds")
        now = datetime.now(timezone.utc)
        candidates: list[ListingItem] = []
        errors: list[EngineError] = []
        seen: set[str] = set()
        for seed in resolve_seeds(request.seeds, request.options):
            parsed = urlsplit(seed)
            if parsed.scheme != "https" or parsed.hostname not in {"85po.net", "www.85po.net"}:
                errors.append(EngineError(ErrorCode.INVALID_REQUEST, "85xo seed must use verified 85po.net host"))
                continue
            old_pages = 0
            for page in range(1, max_pages + 1):
                page_url = seed if page == 1 else f"{seed.rstrip('/')}/{page}/"
                try:
                    html = await self._text(page_url)
                    items = parse_listing(html, page_url, now)
                except EngineError as exc:
                    errors.append(exc)
                    old_pages = 0
                    continue
                dated = [item for item in items if item.published_at is not None]
                within = [item for item in dated if within_days(item.published_at, days, now)]
                if request.options.get("include_undated") is True:
                    within.extend(item for item in items if item.published_at is None)
                if items and len(dated) == len(items) and dated and not within:
                    old_pages += 1
                else:
                    old_pages = 0
                for item in within:
                    if item.video_id not in seen:
                        seen.add(item.video_id)
                        candidates.append(item)
                if not items:
                    break
                if limit and len(candidates) >= limit:
                    candidates = candidates[:limit]
                    break
                if old_pages >= 2:
                    break

        semaphore = asyncio.Semaphore(workers)

        async def resolve(item: ListingItem):
            async with semaphore:
                try:
                    return await self._resolve(item)
                except EngineError as exc:
                    return exc

        resolved = await asyncio.gather(*(resolve(item) for item in candidates))
        plans = tuple(value for value in resolved if isinstance(value, DownloadPlan))
        errors.extend(value for value in resolved if isinstance(value, EngineError))
        return CrawlResult(plans=plans, requested=len(request.seeds) or len(resolve_seeds((), request.options)), discovered=len(candidates), unavailable=len(candidates) - len(plans), errors=tuple(errors))

    async def ranking(self, request: CrawlRequest) -> CrawlResult:
        raise EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, "85xo has no ranking operation")
