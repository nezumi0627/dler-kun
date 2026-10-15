"""Signed Linkex API client with secret redaction and bounded pagination."""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import urlencode

from dler_kun2.domain.errors import EngineError, ErrorCode

from .parser import SharePage, parse_envelope, parse_page

API_BASE = "https://prod.linksvc.xyz"


class JsonResponse(Protocol):
    async def json(self) -> Any: ...


class HttpClient(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> JsonResponse: ...


class LinkexClient:
    def __init__(self, http: HttpClient, api_key: str | None = None, *, clock: Callable[[], float] = time.time):
        self.http = http
        self._api_key = api_key if api_key is not None else os.environ.get("LINKEX_API_KEY", "")
        self._clock = clock

    @staticmethod
    def share_token(url: str) -> str:
        from re import fullmatch
        from urllib.parse import urlsplit

        parsed = urlsplit(url)
        try:
            parsed.port
        except ValueError as exc:
            raise EngineError(ErrorCode.INVALID_REQUEST, "invalid Linkex share URL") from exc
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"l2e.click", "www.l2e.click"} or parsed.username or parsed.password:
            raise EngineError(ErrorCode.INVALID_REQUEST, "invalid Linkex share URL")
        match = fullmatch(r"/i/([A-Za-z0-9_-]{4,128})/?", parsed.path)
        if not match:
            raise EngineError(ErrorCode.INVALID_REQUEST, "invalid Linkex share URL")
        return match.group(1)

    def _headers(self, path_query: str) -> dict[str, str]:
        if not self._api_key:
            raise EngineError(ErrorCode.DEPENDENCY_MISSING, "LINKEX_API_KEY is not configured")
        timestamp = str(int(self._clock()))
        headers = {
            "Content-Type": "application/json",
            "X-LinkInflu-App": "linkex",
            "X-LinkInflu-App-Lang": "ja",
            "X-LinkInflu-Ts": timestamp,
        }
        header_hash = hashlib.md5("&".join(f"{key.lower()}={value}" for key, value in sorted(headers.items())).encode()).hexdigest()
        headers["X-LinkInflu-Sign"] = hashlib.md5(f"path={path_query}&header={header_hash}&body=&key={self._api_key}".encode()).hexdigest()
        return headers

    async def _request(self, path: str, params: dict[str, object]) -> dict[str, Any]:
        from dler_kun2.infrastructure.http.client import HttpError

        query = urlencode(params)
        path_query = f"{path}?{query}" if query else path
        try:
            response = await self.http.request("GET", API_BASE + path_query, headers=self._headers(path_query))
            return parse_envelope(await response.json())
        except HttpError as exc:
            raise EngineError(exc.code, "Linkex API request failed", exc.retry_after) from exc
        except EngineError:
            raise
        except (ValueError, TypeError) as exc:
            raise EngineError(ErrorCode.NETWORK_ERROR, "invalid Linkex API response") from exc

    async def validate_share(self, token: str) -> None:
        await self._request("/api/drive/v1/share/get", {"share_token": token})

    async def list_children(self, token: str, parent: str | None, page: int, page_size: int = 100) -> SharePage:
        from dler_kun2.infrastructure.http.client import HttpError

        if page < 1 or page_size < 1 or page_size > 500:
            raise EngineError(ErrorCode.INVALID_REQUEST, "invalid Linkex pagination")
        params: dict[str, object] = {"share_token": token, "page": page, "page_size": page_size, "need_parents": "true"}
        if parent:
            params["parent_id"] = parent
        query = urlencode(params)
        path_query = f"/api/drive/v1/share/get/content?{query}"
        try:
            response = await self.http.request("GET", API_BASE + path_query, headers=self._headers(path_query))
            return parse_page(await response.json())
        except HttpError as exc:
            raise EngineError(exc.code, "Linkex API request failed", exc.retry_after) from exc
        except EngineError:
            raise
        except (ValueError, TypeError) as exc:
            raise EngineError(ErrorCode.NETWORK_ERROR, "invalid Linkex API response") from exc
