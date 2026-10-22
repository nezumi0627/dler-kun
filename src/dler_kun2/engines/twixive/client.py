"""Small client for TwiXive's public video discovery API."""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import urlencode

from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.infrastructure.http.client import HttpError

API = "https://twixive.net"
SITE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


class JsonResponse(Protocol):
    async def json(self) -> Any: ...


class HttpClient(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> JsonResponse: ...


class TwixiveClient:
    def __init__(self, http: HttpClient):
        self.http = http

    async def _get(self, path: str, params: dict[str, str | int]) -> dict[str, Any]:
        query = urlencode(params)
        try:
            response = await self.http.request(
                "GET",
                f"{API}{path}?{query}",
                headers={
                    "Accept": "application/json",
                    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                    "Origin": API,
                    "Referer": f"{API}/",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin",
                    "User-Agent": SITE_USER_AGENT,
                },
            )
            payload = await response.json()
        except HttpError as exc:
            raise EngineError(exc.code, "TwiXive request failed", exc.retry_after) from exc
        except (ValueError, TypeError) as exc:
            raise EngineError(ErrorCode.NETWORK_ERROR, "invalid TwiXive API response") from exc
        if not isinstance(payload, dict):
            raise EngineError(ErrorCode.NETWORK_ERROR, "invalid TwiXive API response")
        return payload

    async def user_videos(
        self, identifier: str, *, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, str | int] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._get(
            f"/api/users/{identifier}/videos", params
        )

    async def ranking_videos(
        self, *, days: int, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        return await self._get(
            "/api/rankings/video",
            {"kind": "day", "days": days, "limit": limit, "offset": offset},
        )

    async def trend_videos(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return await self._get(
            "/api/rankings/video",
            {"kind": "trend", "limit": limit, "offset": offset},
        )
