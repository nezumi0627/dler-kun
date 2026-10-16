"""Resolve fun800 media and related channels without losing partial results."""

from __future__ import annotations

from collections import deque
from pathlib import PurePosixPath
from typing import Protocol
from urllib.parse import urlsplit

from dler_kun2.domain.contracts import CrawlRequest, DownloadRequest, EngineCapabilities
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import CrawlResult
from dler_kun2.domain.plans import DownloadPlan

from .parser import Entry


class Fun800Api(Protocol):
    async def info(self, domain: str, code: str) -> Entry: ...
    async def list(self, domain: str, code: str, page: int, page_size: int = 50) -> tuple[tuple[Entry, ...], int | None]: ...


def share_code(url: str) -> tuple[str, str]:
    from .parser import _code

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise EngineError(ErrorCode.INVALID_REQUEST, "invalid fun800 URL") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 80, 443}
    ):
        raise EngineError(ErrorCode.INVALID_REQUEST, "invalid fun800 URL")
    host = parsed.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    return host, _code(PurePosixPath(parsed.path).name)


class MvfileEngine:
    engine_id = "mvfile"
    capabilities = EngineCapabilities(download=True, crawl=True)

    def __init__(self, client: Fun800Api):
        self.client = client

    @staticmethod
    def _plan(domain: str, entry: Entry) -> DownloadPlan:
        if not entry.media_url:
            raise EngineError(ErrorCode.NOT_FOUND, "source media unavailable")
        suffix = PurePosixPath(urlsplit(entry.media_url).path).suffix.lower()
        kind = "hls" if suffix == ".m3u8" else "direct"
        extension = ".mp4" if kind == "hls" else suffix if suffix in {".mp4", ".mov", ".webm", ".m4v", ".mkv"} else ".mp4"
        name = entry.name if entry.name.lower().endswith(extension) else f"{entry.name}{extension}"
        page = f"https://{domain}/d/{entry.code}"
        return DownloadPlan(entry.media_url, page, page, kind, name, entry.size, {"share_code": entry.code})

    async def resolve_download(self, request: DownloadRequest) -> DownloadPlan:
        domain, code = share_code(request.url)
        item = await self.client.info(domain, code)
        if item.folder:
            raise EngineError(ErrorCode.INVALID_REQUEST, "folder URL requires crawl")
        return self._plan(domain, item)

    async def resolve_many(self, request: DownloadRequest) -> CrawlResult:
        if request.options.get("single"):
            plan = await self.resolve_download(request)
            return CrawlResult(plans=(plan,), requested=1, discovered=1)
        return await self.crawl(CrawlRequest(self.engine_id, (request.url,), None, request.options))

    async def crawl(self, request: CrawlRequest) -> CrawlResult:
        seeds = request.seeds
        try:
            raw_max_pages = request.options.get("max_pages")
            max_pages = 50 if raw_max_pages is None else int(raw_max_pages)
        except (TypeError, ValueError) as exc:
            raise EngineError(ErrorCode.INVALID_REQUEST, "mvfile max_pages must be an integer") from exc
        if not 1 <= max_pages <= 500:
            raise EngineError(ErrorCode.INVALID_REQUEST, "max_pages must be 1..500")
        plans: list[DownloadPlan] = []
        errors: list[EngineError] = []
        seen: set[tuple[str, str]] = set()
        unavailable = 0
        for seed in seeds:
            try:
                domain, code = share_code(seed)
                root = await self.client.info(domain, code)
                original = root
                if root.channel and root.channel != root.code:
                    root = await self.client.info(domain, root.channel)
                queue = deque([root])
                if not original.folder and original.code != root.code:
                    queue.append(original)
                while queue:
                    item = queue.popleft()
                    identity = (domain, item.code)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    if item.folder or (item is root and root.code != code):
                        page = 1
                        while page <= max_pages:
                            try:
                                entries, total = await self.client.list(domain, item.code, page)
                            except EngineError as exc:
                                errors.append(exc)
                                break
                            if not entries:
                                break
                            queue.extend(entries)
                            if total is not None and page * 50 >= total:
                                break
                            if len(entries) < 50 and total is None:
                                break
                            page += 1
                        else:
                            errors.append(EngineError(ErrorCode.CRAWL_FAILED, "pagination limit reached"))
                    else:
                        try:
                            resolved = item if item.media_url else await self.client.info(domain, item.code)
                            plans.append(self._plan(domain, resolved))
                        except EngineError as exc:
                            if exc.code is ErrorCode.NOT_FOUND:
                                unavailable += 1
                            else:
                                errors.append(exc)
            except EngineError as exc:
                errors.append(exc)
        return CrawlResult(plans=tuple(plans), requested=len(seeds), discovered=len(plans) + unavailable, unavailable=unavailable, errors=tuple(errors))

    async def ranking(self, request: CrawlRequest) -> CrawlResult:
        raise EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, "mvfile has no ranking")
