"""TwiXive profile, ranking, and randomized Reels crawl support."""

from __future__ import annotations

import random
import re
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.parse import urlsplit

from dler_kun2.domain.contracts import CrawlRequest, DownloadRequest, EngineCapabilities
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import CrawlResult
from dler_kun2.domain.plans import DownloadPlan
from dler_kun2.domain.types import EngineOptions, int_option

VIDEO_PAGE_SIZE = 50
RANKING_MAX_ITEMS = 500
DEFAULT_REELS_COUNT = 20
MAX_REELS_COUNT = 500
_IDENTIFIER = re.compile(r"[A-Za-z0-9_]{1,64}\Z")
_VIDEO_ID = re.compile(r"[0-9]{1,32}\Z")


class TwixiveApi(Protocol):
    async def user_videos(
        self, identifier: str, *, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]: ...

    async def ranking_videos(
        self, *, days: int, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]: ...

    async def trend_videos(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]: ...


def _route(url: str) -> tuple[str, str | None]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise EngineError(ErrorCode.INVALID_REQUEST, "invalid TwiXive URL") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"twixive.net", "www.twixive.net"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 80, 443}
    ):
        raise EngineError(ErrorCode.INVALID_REQUEST, "invalid TwiXive URL")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) == 2 and parts[0] == "user" and _IDENTIFIER.fullmatch(parts[1]):
        return "user", parts[1]
    if len(parts) == 2 and parts[0] == "ranking" and parts[1] in {"24h", "3days", "7days"}:
        return "ranking", parts[1]
    if parsed.path.rstrip("/") == "/reels":
        return "reels", None
    raise EngineError(ErrorCode.INVALID_REQUEST, "unsupported TwiXive page")


def _entries(payload: dict[str, Any], *, ranked: bool) -> tuple[dict[str, Any], ...]:
    raw = payload.get("items") if ranked else payload.get("videos")
    if not isinstance(raw, list):
        raise EngineError(ErrorCode.NETWORK_ERROR, "TwiXive response has no video list")
    entries: list[dict[str, Any]] = []
    for item in raw:
        video = item.get("video") if ranked and isinstance(item, dict) else item
        if isinstance(video, dict):
            entries.append(video)
    return tuple(entries)


def _plan(video: dict[str, Any], page_url: str) -> DownloadPlan | None:
    media_url = video.get("url")
    video_id = video.get("id")
    if not isinstance(media_url, str) or not isinstance(video_id, str) or not _VIDEO_ID.fullmatch(video_id):
        return None
    try:
        media = urlsplit(media_url)
        port = media.port
    except ValueError:
        return None
    if (
        media.scheme != "https"
        or media.hostname != "video.twimg.com"
        or media.username is not None
        or media.password is not None
        or port not in {None, 443}
    ):
        return None
    suffix = PurePosixPath(media.path).suffix.lower()
    if suffix not in {".mp4", ".mov", ".m4v", ".webm"}:
        return None
    return DownloadPlan(
        media_url,
        page_url,
        page_url,
        suffix[1:],
        f"{video_id}{suffix}",
        None,
        {"video_id": video_id},
    )


class TwixiveEngine:
    engine_id = "twixive"
    capabilities = EngineCapabilities(download=True, crawl=True)

    def __init__(self, client: TwixiveApi):
        self.client = client

    async def resolve_download(self, request: DownloadRequest) -> DownloadPlan:
        result = await self.resolve_many(request)
        if result.errors:
            raise result.errors[0]
        if len(result.plans) != 1:
            raise EngineError(ErrorCode.INVALID_REQUEST, "TwiXive page contains multiple videos; use crawl")
        return result.plans[0]

    async def resolve_many(self, request: DownloadRequest) -> CrawlResult:
        return await self._crawl_url(request.url, request.options)

    async def crawl(self, request: CrawlRequest) -> CrawlResult:
        if not request.seeds:
            raise EngineError(ErrorCode.INVALID_REQUEST, "TwiXive crawl requires a user, ranking, or reels URL")
        results: list[CrawlResult] = []
        for seed in request.seeds:
            try:
                results.append(await self._crawl_url(seed, request.options))
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
        return await self.crawl(request)

    async def _crawl_url(self, url: str, options: EngineOptions) -> CrawlResult:
        kind, value = _route(url)
        canonical = f"https://twixive.net{urlsplit(url).path.rstrip('/') or '/'}"
        if kind == "user":
            return await self._user(value or "", canonical, options)
        if kind == "ranking":
            days = {"24h": 1, "3days": 3, "7days": 7}[value or "24h"]
            return await self._ranking(days, canonical, options)
        return await self._reels(canonical, options)

    async def _user(self, identifier: str, page_url: str, options: EngineOptions) -> CrawlResult:
        max_pages = _bounded_int(options, "max_pages", 500, 1, 500)
        limit = _bounded_int(options, "limit", 0, 0, RANKING_MAX_ITEMS)
        cursor: str | None = None
        seen_cursors: set[str] = set()
        videos: list[dict[str, Any]] = []
        errors: list[EngineError] = []
        unavailable = 0
        for _ in range(max_pages):
            payload = await self.client.user_videos(identifier, limit=VIDEO_PAGE_SIZE, cursor=cursor)
            page_videos = _entries(payload, ranked=False)
            videos.extend(page_videos)
            page_info = payload.get("pageInfo")
            if not isinstance(page_info, dict) or not isinstance(page_info.get("hasNextPage"), bool):
                errors.append(EngineError(ErrorCode.NETWORK_ERROR, "TwiXive response has invalid pagination data"))
                break
            if page_info["hasNextPage"] is False:
                break
            next_cursor = page_info.get("nextCursor")
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                errors.append(EngineError(ErrorCode.CRAWL_FAILED, "TwiXive user pagination returned an invalid cursor"))
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        else:
            errors.append(EngineError(ErrorCode.CRAWL_FAILED, "TwiXive user pagination limit reached"))
        if limit:
            videos = videos[:limit]
        plans, invalid = _plans(videos, page_url)
        unavailable += invalid
        return CrawlResult(plans=plans, requested=1, discovered=len(videos), unavailable=unavailable, errors=tuple(errors))

    async def _ranking(self, days: int, page_url: str, options: EngineOptions) -> CrawlResult:
        limit = _bounded_int(options, "limit", RANKING_MAX_ITEMS, 1, RANKING_MAX_ITEMS)
        videos: list[dict[str, Any]] = []
        for offset in range(0, limit, VIDEO_PAGE_SIZE):
            payload = await self.client.ranking_videos(
                days=days, limit=min(VIDEO_PAGE_SIZE, limit - offset), offset=offset
            )
            page = _entries(payload, ranked=True)
            videos.extend(page)
            if len(page) < min(VIDEO_PAGE_SIZE, limit - offset):
                break
        plans, unavailable = _plans(videos, page_url)
        return CrawlResult(plans=plans, requested=1, discovered=len(videos), unavailable=unavailable)

    async def _reels(self, page_url: str, options: EngineOptions) -> CrawlResult:
        count = _bounded_int(options, "limit", DEFAULT_REELS_COUNT, 1, MAX_REELS_COUNT)
        pool: list[dict[str, Any]] = []
        for offset in range(0, MAX_REELS_COUNT, VIDEO_PAGE_SIZE):
            payload = await self.client.trend_videos(limit=VIDEO_PAGE_SIZE, offset=offset)
            page = _entries(payload, ranked=True)
            pool.extend(page)
            if len(page) < VIDEO_PAGE_SIZE:
                break
        unique: dict[str, dict[str, Any]] = {}
        for video in pool:
            video_id = video.get("id")
            if isinstance(video_id, str) and _VIDEO_ID.fullmatch(video_id):
                unique.setdefault(video_id, video)
        candidates = list(unique.values())
        candidates = [video for video in candidates if _plan(video, page_url) is not None]
        selected = random.SystemRandom().sample(candidates, min(count, len(candidates)))
        plans, unavailable = _plans(selected, page_url)
        return CrawlResult(plans=plans, requested=1, discovered=len(selected), unavailable=unavailable)


def _plans(videos: list[dict[str, Any]], page_url: str) -> tuple[tuple[DownloadPlan, ...], int]:
    plans: list[DownloadPlan] = []
    unavailable = 0
    seen: set[str] = set()
    for video in videos:
        video_id = video.get("id")
        if isinstance(video_id, str) and video_id in seen:
            continue
        if isinstance(video_id, str):
            seen.add(video_id)
        plan = _plan(video, page_url)
        if plan is None:
            unavailable += 1
        else:
            plans.append(plan)
    return tuple(plans), unavailable


def _bounded_int(options: EngineOptions, name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int_option(options, name, default)
    except (TypeError, ValueError) as exc:
        raise EngineError(ErrorCode.INVALID_REQUEST, f"TwiXive {name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise EngineError(ErrorCode.INVALID_REQUEST, f"TwiXive {name} must be {minimum}..{maximum}")
    return value
