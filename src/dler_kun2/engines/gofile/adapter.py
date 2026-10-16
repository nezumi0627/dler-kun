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
    capabilities = EngineCapabilities(download=True, crawl=True, ranking=True)

    def __init__(self, client: Api):
        self.client = client

    async def _discover(self, url: str, password: str | None, max_pages: int = 100) -> CrawlResult:
        if not 1 <= max_pages <= 500:
            raise EngineError(ErrorCode.INVALID_REQUEST, "GoFile max_pages must be 1..500")
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
                pagination = payload.get("metadata") if isinstance(payload, dict) else None
                if not isinstance(pagination, dict):
                    pagination = data.get("pagination", {}) if isinstance(data, dict) else {}
                total_pages = pagination.get("totalPages", pagination.get("pages")) if isinstance(pagination, dict) else None
                raw_children = data.get("children", {}) if isinstance(data, dict) else {}
                raw_count = len(raw_children) if isinstance(raw_children, dict) else 0
                has_next = pagination.get("hasNextPage") if isinstance(pagination, dict) else None
                if (
                    not items
                    or has_next is False
                    or (isinstance(total_pages, int) and page >= total_pages)
                    or (has_next is None and total_pages is None and raw_count < 1000)
                ):
                    break
            else:
                errors.append(EngineError(ErrorCode.CRAWL_FAILED, "GoFile pagination limit reached"))
        return CrawlResult(plans=tuple(plans), requested=1, discovered=discovered, unavailable=unavailable, errors=tuple(errors))

    async def resolve_many(self, request: DownloadRequest) -> CrawlResult:
        from .ranking import is_ranking_source_url

        if is_ranking_source_url(request.url):
            return await self.ranking(CrawlRequest(self.engine_id, (request.url,), None, request.options))
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
            return await self.ranking(request)
        from .ranking import is_ranking_source_url, normalize_sources

        normalized = normalize_sources(request.seeds)
        if normalized and all(is_ranking_source_url(seed) for seed in normalized):
            return await self.ranking(CrawlRequest(self.engine_id, normalized, request.days, request.options))
        try:
            max_pages = int(request.options.get("max_pages", 100))
        except (TypeError, ValueError) as exc:
            raise EngineError(ErrorCode.INVALID_REQUEST, "GoFile max_pages must be an integer") from exc
        results = []
        for seed in request.seeds:
            password = request.options.get("password")
            try:
                results.append(await self._discover(seed, str(password) if password else None, max_pages))
            except EngineError as exc:
                results.append(CrawlResult(requested=1, errors=(exc,)))
        return CrawlResult(plans=tuple(p for result in results for p in result.plans), requested=len(request.seeds), discovered=sum(r.discovered for r in results), unavailable=sum(r.unavailable for r in results), errors=tuple(e for r in results for e in r.errors))

    async def ranking(self, request: CrawlRequest) -> CrawlResult:
        from .ranking import DEFAULT_RANKING_SOURCES, fetch_ids, normalize_sources
        plans: list[DownloadPlan] = []
        errors: list[EngineError] = []
        requested = discovered = unavailable = 0
        seen: set[str] = set()
        try:
            limit = int(request.options.get("limit", 60))
        except (TypeError, ValueError) as exc:
            raise EngineError(ErrorCode.INVALID_REQUEST, "GoFile ranking limit must be an integer") from exc
        if not 1 <= limit <= 500:
            raise EngineError(ErrorCode.INVALID_REQUEST, "GoFile ranking limit must be 1..500")
        http = getattr(self.client, "http", None)
        if http is None:
            raise EngineError(ErrorCode.DEPENDENCY_MISSING, "GoFile ranking HTTP client is unavailable")
        if request.seeds:
            seeds = request.seeds
        else:
            seeds = DEFAULT_RANKING_SOURCES
        for seed in normalize_sources(seeds):
            requested += 1
            try:
                ids = await fetch_ids(http, seed, limit=limit)
            except EngineError as exc:
                errors.append(exc)
                continue
            except Exception as exc:
                from dler_kun2.infrastructure.http.client import HttpError

                if isinstance(exc, HttpError):
                    errors.append(EngineError(exc.code, "GoFile ranking request failed", exc.retry_after))
                else:
                    errors.append(EngineError(ErrorCode.NETWORK_ERROR, "GoFile ranking request failed"))
                continue
            for item_id in ids:
                if item_id in seen:
                    continue
                seen.add(item_id)
                result = await self._discover(f"https://gofile.io/d/{item_id}", None)
                plans.extend(result.plans)
                discovered += result.discovered
                unavailable += result.unavailable
                errors.extend(result.errors)
        return CrawlResult(plans=tuple(plans), requested=requested, discovered=discovered, unavailable=unavailable, errors=tuple(errors))
