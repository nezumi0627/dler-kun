"""Videy page resolver implementing the v2 engine contract."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from dler_kun2.domain.contracts import (
    CrawlRequest,
    DownloadRequest,
    EngineCapabilities,
)
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import CrawlResult
from dler_kun2.domain.plans import DownloadPlan

from .parser import parse_player


class TextResponse(Protocol):
    async def text(self) -> str: ...


class HttpClient(Protocol):
    async def request(self, method: str, url: str) -> TextResponse: ...


class VideyEngine:
    engine_id = "videy"
    capabilities = EngineCapabilities(download=True)

    def __init__(self, http: HttpClient | None = None):
        self._http = http

    async def resolve_download(self, request: DownloadRequest) -> DownloadPlan:
        if self._http is None:
            raise EngineError(ErrorCode.DEPENDENCY_MISSING, "HTTP runtime is unavailable")
        try:
            response = await self._http.request("GET", request.url)
            html = await response.text()
            video_id, media_url, extension = parse_player(request.url, html, "")
        except Exception as exc:
            from dler_kun2.infrastructure.http.client import HttpError

            if isinstance(exc, HttpError):
                raise EngineError(exc.code, "Videy page request failed", exc.retry_after) from exc
            if isinstance(exc, ValueError):
                code = ErrorCode.INVALID_REQUEST if str(exc).startswith("invalid") else ErrorCode.NOT_FOUND
                raise EngineError(code, "Videy URL could not be resolved") from exc
            raise EngineError(ErrorCode.NETWORK_ERROR, "Videy page request failed") from exc
        parsed_request = urlunsplit(("https", urlsplit(request.url).hostname or "videy.co", urlsplit(request.url).path, "", ""))
        if urlsplit(request.url).hostname in {"videy.co", "www.videy.co"}:
            parsed_request = urlunsplit(("https", "videy.co", "/v", f"id={video_id}", ""))
        return DownloadPlan(
            media_url=media_url,
            source_url=parsed_request,
            source_page=parsed_request,
            media_kind=extension,
            suggested_name=f"{video_id}.{extension}",
            size=None,
            metadata={"video_id": video_id},
        )

    async def crawl(self, request: CrawlRequest) -> CrawlResult:
        raise EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, "Videy does not support crawling")

    async def ranking(self, request: CrawlRequest) -> CrawlResult:
        raise EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, "Videy does not support ranking")
