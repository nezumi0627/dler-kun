"""Asynchronous fun800 client using the shared HTTP runtime."""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import urlencode

from dler_kun2.domain.errors import EngineError, ErrorCode

from .parser import Entry, parse_info, parse_list

DEFAULT_API = "https://rwzugqnp.fun800.click/app-api"


class JsonResponse(Protocol):
    async def json(self) -> Any: ...


class HttpClient(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> JsonResponse: ...


class Fun800Client:
    def __init__(self, http: HttpClient, api_base: str = DEFAULT_API):
        self.http = http
        self.api_base = api_base.rstrip("/")

    async def _get(self, domain: str, endpoint: str, code: str, **params: int) -> Any:
        from dler_kun2.infrastructure.http.client import HttpError

        arguments = {"externalLinks": code, "domain": domain, **params}
        if domain in {"gofile.bar", "gofile.pl"}:
            base = "https://gofile.bar/api.php" if domain == "gofile.bar" else "https://gofile.pl/api.php"
            url = f"{base}?{urlencode({'endpoint': '/flow/land-page/' + endpoint, **arguments})}"
        else:
            url = f"{self.api_base}/flow/land-page/{endpoint}?{urlencode(arguments)}"
        try:
            response = await self.http.request("GET", url, headers={"Referer": f"https://{domain}/", "Accept": "application/json"})
            return await response.json()
        except HttpError as exc:
            raise EngineError(exc.code, "fun800 API request failed", exc.retry_after) from exc
        except (ValueError, TypeError) as exc:
            raise EngineError(ErrorCode.NETWORK_ERROR, "invalid fun800 JSON response") from exc

    async def info(self, domain: str, code: str) -> Entry:
        return parse_info(await self._get(domain, "getInfo", code), code)

    async def list(self, domain: str, code: str, page: int, page_size: int = 50) -> tuple[tuple[Entry, ...], int | None]:
        return parse_list(await self._get(domain, "list_by_links_page", code, pageNo=page, pageSize=page_size, sortOrder=2))
