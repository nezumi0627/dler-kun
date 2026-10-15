"""Resolve and download shared Linkex files using the shared transfer boundary."""

from __future__ import annotations

from collections import deque
from pathlib import PurePosixPath
from typing import Protocol
from urllib.parse import urlsplit

from dler_kun2.domain.contracts import CrawlRequest, DownloadRequest, EngineCapabilities
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import CrawlResult
from dler_kun2.domain.plans import DownloadPlan

from .parser import SharePage


class Api(Protocol):
    @staticmethod
    def share_token(url: str) -> str: ...
    async def validate_share(self, token: str) -> None: ...
    async def list_children(self, token: str, parent: str | None, page: int, page_size: int = 100) -> SharePage: ...


class LinkexEngine:
    engine_id = "linkex"
    capabilities = EngineCapabilities(download=True, crawl=True)

    def __init__(self, client: Api):
        self.client = client

    async def _plans(self, url: str, max_pages: int = 100) -> CrawlResult:
        token = self.client.share_token(url)
        await self.client.validate_share(token)
        queue = deque([None])
        folders: set[str] = set()
        plans: list[DownloadPlan] = []
        errors: list[EngineError] = []
        unavailable = 0
        discovered = 0
        while queue:
            parent = queue.popleft()
            page_number = 1
            while page_number <= max_pages:
                try:
                    page = await self.client.list_children(token, parent, page_number)
                except EngineError as exc:
                    errors.append(exc)
                    break
                discovered += len(page.items)
                for item in page.items:
                    if item.kind in {"dir", "directory", "folder"}:
                        if item.item_id not in folders:
                            folders.add(item.item_id)
                            queue.append(item.item_id)
                        continue
                    if not item.media_url:
                        unavailable += 1
                        continue
                    suffix = PurePosixPath(urlsplit(item.media_url).path).suffix.lower()
                    kind = suffix.lstrip(".") if suffix else "binary"
                    plans.append(DownloadPlan(item.media_url, "https://l2e.click/", "https://l2e.click/", kind, item.name, None, {"item_id": item.item_id}))
                if page.has_more is False or (page.total is not None and page_number * 100 >= page.total) or not page.items:
                    break
                if page.has_more is None and page.total is None and len(page.items) < 100:
                    break
                page_number += 1
            else:
                errors.append(EngineError(ErrorCode.CRAWL_FAILED, "Linkex pagination limit reached"))
        return CrawlResult(plans=tuple(plans), requested=1, discovered=discovered, unavailable=unavailable, errors=tuple(errors))

    async def resolve_download(self, request: DownloadRequest) -> DownloadPlan:
        result = await self._plans(request.url)
        if result.errors:
            raise result.errors[0]
        if not result.plans:
            raise EngineError(ErrorCode.NOT_FOUND, "Linkex share contains no downloadable files")
        if len(result.plans) > 1:
            raise EngineError(ErrorCode.INVALID_REQUEST, "share contains multiple files; use crawl")
        return result.plans[0]

    async def resolve_many(self, request: DownloadRequest) -> CrawlResult:
        return await self._plans(request.url)

    async def crawl(self, request: CrawlRequest) -> CrawlResult:
        if not request.seeds:
            raise EngineError(ErrorCode.INVALID_REQUEST, "Linkex share URL is required")
        results = []
        for seed in request.seeds:
            try:
                results.append(await self._plans(seed, int(request.options.get("max_pages", 100))))
            except EngineError as exc:
                results.append(CrawlResult(requested=1, errors=(exc,)))
        return CrawlResult(
            plans=tuple(plan for result in results for plan in result.plans),
            requested=len(request.seeds),
            discovered=sum(result.discovered for result in results),
            unavailable=sum(result.unavailable for result in results),
            errors=tuple(error for result in results for error in result.errors),
        )

    async def ranking(self, request: CrawlRequest) -> CrawlResult:
        raise EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, "Linkex has no ranking operation")
