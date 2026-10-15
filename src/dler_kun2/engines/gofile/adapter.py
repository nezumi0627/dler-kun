"""GoFile recursive discovery adapter; transfers are delegated to the application."""

from __future__ import annotations

from collections import deque
from typing import Any, Protocol
from urllib.parse import urlsplit

from dler_kun2.domain.contracts import CrawlRequest, DownloadRequest, EngineCapabilities
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import CrawlResult
from dler_kun2.domain.plans import DownloadPlan

from .parser import content_id, parse_content


class Api(Protocol):
    async def content(self, content_id: str, *, password: str | None = None, page: int = 1, page_size: int = 1000) -> Any: ...


class GoFileEngine:
    engine_id = "gofile"
    capabilities = EngineCapabilities(download=True, crawl=True)

    def __init__(self, client: Api):
        self.client = client

    async def _discover(self, url: str, password: str | None, max_pages: int = 100) -> CrawlResult:
        root_id = content_id(url)
        queue = deque([(root_id, "", password)])
        visited: set[str] = set()
        plans: list[DownloadPlan] = []
        errors: list[EngineError] = []
        discovered = unavailable = 0
        while queue:
            current_id, parent_name, current_password = queue.popleft()
            if current_id in visited:
                continue
            visited.add(current_id)
            for page in range(1, max_pages + 1):
                try:
                    payload = await self.client.content(current_id, password=current_password if page == 1 else None, page=page)
                    items = parse_content(payload)
                    data = payload.get("data", {}) if isinstance(payload, dict) else {}
                except EngineError as exc:
                    errors.append(exc)
                    break
                discovered += len(items)
                for item in items:
                    relative_name = "/".join(part for part in (parent_name, item.name) if part)
                    if item.kind == "folder":
                        queue.append((item.item_id, relative_name, None))
                    elif not item.media_url:
                        unavailable += 1
                    else:
                        source = f"https://gofile.io/d/{root_id}"
                        path = urlsplit(item.media_url).path
                        extension = path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else "bin"
                        plans.append(DownloadPlan(item.media_url, source, source, extension, item.name, item.size, {"file_id": item.item_id, "relative_dir": parent_name}))
                pagination = data.get("pagination", {}) if isinstance(data, dict) else {}
                total_pages = pagination.get("pages") if isinstance(pagination, dict) else None
                raw_children = data.get("children", {}) if isinstance(data, dict) else {}
                raw_count = len(raw_children) if isinstance(raw_children, dict) else 0
                has_next = pagination.get("hasNextPage") if isinstance(pagination, dict) else None
                if not items or has_next is False or (isinstance(total_pages, int) and page >= total_pages) or raw_count < 1000:
                    break
            else:
                errors.append(EngineError(ErrorCode.CRAWL_FAILED, "GoFile pagination limit reached"))
        return CrawlResult(plans=tuple(plans), requested=1, discovered=discovered, unavailable=unavailable, errors=tuple(errors))

    async def resolve_many(self, request: DownloadRequest) -> CrawlResult:
        password = request.options.get("password")
        return await self._discover(request.url, str(password) if password else None)

    async def resolve_download(self, request: DownloadRequest) -> DownloadPlan:
        result = await self.resolve_many(request)
        if result.errors:
            raise result.errors[0]
        if len(result.plans) != 1:
            raise EngineError(ErrorCode.INVALID_REQUEST, "GoFile share contains multiple files; use crawl")
        return result.plans[0]

    async def crawl(self, request: CrawlRequest) -> CrawlResult:
        if not request.seeds:
            raise EngineError(ErrorCode.INVALID_REQUEST, "GoFile share URL is required")
        results = []
        for seed in request.seeds:
            password = request.options.get("password")
            try:
                results.append(await self._discover(seed, str(password) if password else None, int(request.options.get("max_pages", 100))))
            except EngineError as exc:
                results.append(CrawlResult(requested=1, errors=(exc,)))
        return CrawlResult(plans=tuple(p for result in results for p in result.plans), requested=len(request.seeds), discovered=sum(r.discovered for r in results), unavailable=sum(r.unavailable for r in results), errors=tuple(e for r in results for e in r.errors))

    async def ranking(self, request: CrawlRequest) -> CrawlResult:
        raise EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, "GoFile ranking sources are pending migration")
