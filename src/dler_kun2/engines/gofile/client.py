"""Official GoFile public API client with conservative rate-limit handling."""

from __future__ import annotations

import asyncio
import email.utils
import hashlib
import math
import os
import time
from typing import Any, Protocol
from urllib.parse import urlencode

from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.infrastructure.http.client import HttpError

from .browser_token import BrowserWebsiteTokenProvider
from .token_store import GuestTokenStore

API = "https://api.gofile.io"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149.0.0.0 Safari/537.36"


class JsonResponse(Protocol):
    headers: Any
    async def json(self) -> Any: ...


class HttpClient(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> JsonResponse: ...


class WebsiteTokenProvider(Protocol):
    async def generate(self, account_token: str) -> tuple[str, str, str]: ...


class GoFileClient:
    def __init__(self, http: HttpClient, token_store: GuestTokenStore | None = None, *, clock=time.time, website_token_provider: WebsiteTokenProvider | None = None):
        self.http = http
        self.token_store = token_store or GuestTokenStore()
        self._clock = clock
        self._token: str | None = os.environ.get("GF_TOKEN") or os.environ.get("GOFILE_TOKEN")
        self._token_lock = asyncio.Lock()
        self._wt_lock = asyncio.Lock()
        self._website_token_provider = website_token_provider or BrowserWebsiteTokenProvider()
        self._cached_wt: tuple[int, str, str, str] | None = None

    async def _website_token(self, account_token: str) -> tuple[str, str, str]:
        async with self._wt_lock:
            timeblock = math.floor(self._clock() / 14400)
            if self._cached_wt and self._cached_wt[0] == timeblock:
                return self._cached_wt[1:]
            for _attempt in range(2):
                before = math.floor(self._clock() / 14400)
                wt, user_agent, language = await self._website_token_provider.generate(account_token)
                after = math.floor(self._clock() / 14400)
                if before == after:
                    self._cached_wt = (after, wt, user_agent, language)
                    return wt, user_agent, language
            raise EngineError(ErrorCode.NETWORK_ERROR, "GoFile signing crossed a time-block boundary")

    @staticmethod
    def _headers(token: str, website_token: str, user_agent: str, language: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "X-Website-Token": website_token,
            "X-BL": language,
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Accept-Language": language,
            "Origin": "https://gofile.io",
            "Referer": "https://gofile.io/",
        }

    @staticmethod
    def _check_http_error(exc: HttpError) -> EngineError:
        return EngineError(exc.code, "GoFile API request failed", exc.retry_after)

    async def account_token(self) -> str:
        if self._token:
            return self._token
        async with self._token_lock:
            if self._token:
                return self._token
            self._token = self.token_store.load()
            if self._token:
                return self._token
            try:
                response = await self.http.request("POST", f"{API}/accounts", headers={"Accept": "application/json", "Origin": "https://gofile.io", "Referer": "https://gofile.io/", "User-Agent": USER_AGENT})
                payload = await response.json()
            except HttpError as exc:
                raise self._check_http_error(exc) from exc
            except (ValueError, TypeError) as exc:
                raise EngineError(ErrorCode.NETWORK_ERROR, "invalid GoFile account response") from exc
            if not isinstance(payload, dict) or payload.get("status") != "ok" or not isinstance(payload.get("data"), dict):
                raise EngineError(ErrorCode.NETWORK_ERROR, "GoFile guest account could not be created")
            token = payload["data"].get("token")
            if not isinstance(token, str) or not token:
                raise EngineError(ErrorCode.NETWORK_ERROR, "GoFile account response has no token")
            self._token = self.token_store.save(token)
            return self._token

    async def content(self, content_id: str, *, password: str | None = None, page: int = 1, page_size: int = 1000):
        token = await self.account_token()
        params: dict[str, str] = {
            "contentFilter": "",
            "page": str(page),
            "pageSize": str(page_size),
            "sortField": "createTime",
            "sortDirection": "-1",
            "cache": "true",
        }
        if password:
            params["password"] = hashlib.sha256(password.encode()).hexdigest()
        url = f"{API}/contents/{content_id}?{urlencode(params)}"
        try:
            wt, user_agent, language = await self._website_token(token)
            headers = self._headers(token, wt, user_agent, language)
            response = await self.http.request("GET", url, headers=headers)
            payload = await response.json()
        except HttpError as exc:
            raise self._check_http_error(exc) from exc
        except (ValueError, TypeError) as exc:
            raise EngineError(ErrorCode.NETWORK_ERROR, "invalid GoFile content response") from exc
        if isinstance(payload, dict):
            errors = payload.get("errors", [])
            if payload.get("status") == "error-rateLimit" or (isinstance(errors, (list, tuple, set, str)) and "error-rateLimit" in errors):
                raise EngineError(ErrorCode.RATE_LIMITED, "GoFile rate limit reached", _retry_after(response.headers, payload))
        return payload


def _retry_after(headers: Any, payload: dict[str, Any]) -> float | None:
    raw = headers.get("Retry-After") if headers is not None else None
    if raw is None:
        raw = payload.get("retryAfter") or payload.get("retry_after")
    if raw is None:
        return None
    try:
        value = float(raw)
        return max(0.0, value) if math.isfinite(value) else None
    except (TypeError, ValueError):
        try:
            date = email.utils.parsedate_to_datetime(str(raw))
            if date.tzinfo is None:
                from datetime import timezone

                date = date.replace(tzinfo=timezone.utc)
            return max(0.0, date.timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None
