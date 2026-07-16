"""gofile-douga.com ranking/new JSON API helpers.

Page URL → API mapping:

- ``https://gofile-douga.com/new`` → ``/api/new?limit=N``
- ``https://gofile-douga.com/`` → ``/api/rankings?tab=12h&limit=N``
- ``https://gofile-douga.com/?sort=24h`` → ``/api/rankings?tab=24h&limit=N``
- ``https://gofile-douga.com/?sort=3days`` → ``/api/rankings?tab=3d&limit=N``

The home page default uses ``tab=12h`` (12-hour ranking). The public API rejects
``/api/rankings`` without a ``tab`` parameter (HTTP 400); the site frontend also
defaults to ``12h`` when no ``sort`` query is present.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

if TYPE_CHECKING:
    import aiohttp

DOUGA_BASE = "https://gofile-douga.com"
DOUGA_SOURCE_KEYS = ("new", "home", "24h", "3days")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_HOME_TAB = "12h"
RANKING_TAB_BY_SOURCE: dict[str, str] = {
    "home": DEFAULT_HOME_TAB,
    "24h": "24h",
    "3days": "3d",
}

DOUGA_JSON_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
    "Accept-Language": "ja,en-US;q=0.9",
    "Referer": f"{DOUGA_BASE}/",
}

DOUGA_PAGE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ja,en-US;q=0.9",
    "Referer": f"{DOUGA_BASE}/",
}

DEFAULT_REQUEST_TIMEOUT_SECONDS = 15.0
ALIVE_CHECK_TIMEOUT_SECONDS = 5.0


class DougaFetchError(Exception):
    """Raised when a gofile-douga JSON API request fails."""

    def __init__(self, message: str, *, url: str, status: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status = status


def normalize_douga_source(source: str) -> str:
    key = str(source).strip().lower()
    aliases = {
        "3d": "3days",
        "3day": "3days",
        "3days": "3days",
        "default": "home",
        "12h": "home",
        "ranking": "home",
    }
    normalized = aliases.get(key, key)
    if normalized not in DOUGA_SOURCE_KEYS:
        raise ValueError(f"unsupported gofile-douga source: {source!r}")
    return normalized


def resolve_douga_api_url(source: str, limit: int = 60) -> str:
    normalized = normalize_douga_source(source)
    safe_limit = max(1, int(limit))
    if normalized == "new":
        return f"{DOUGA_BASE}/api/new?limit={safe_limit}"
    tab = RANKING_TAB_BY_SOURCE[normalized]
    return f"{DOUGA_BASE}/api/rankings?tab={tab}&limit={safe_limit}"


def parse_douga_seed(seed: str) -> str | None:
    """Map a gofile-douga seed URL to a source key, or ``None`` if unrelated."""
    parsed = urlparse(str(seed).strip())
    host = (parsed.hostname or "").lower()
    if host not in {"gofile-douga.com", "www.gofile-douga.com"}:
        return None

    path = parsed.path.rstrip("/") or "/"
    query = parse_qs(parsed.query)
    sort = (query.get("sort") or [""])[0].strip().lower()
    tab = (query.get("tab") or [""])[0].strip().lower()

    if path.endswith("/new"):
        return "new"

    if path in {"/", "/ranking"}:
        ranking_key = _ranking_key_from_query(sort=sort, tab=tab)
        return ranking_key or "home"

    return None


def _ranking_key_from_query(*, sort: str, tab: str) -> str | None:
    candidate = sort or tab
    if not candidate:
        return None
    if candidate in {"24h", "1h", "3h", "1d"}:
        return "24h"
    if candidate in {"3days", "3d"}:
        return "3days"
    if candidate == "12h":
        return "home"
    return None


def _dedupe_gofile_urls(items: list[object]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        gofile_url = str(item.get("gofileUrl") or "").strip()
        if not gofile_url or gofile_url in seen:
            continue
        seen.add(gofile_url)
        urls.append(gofile_url)
    return urls


async def fetch_douga_urls(
    session: aiohttp.ClientSession,
    source: str,
    limit: int = 60,
) -> list[str]:
    api_url = resolve_douga_api_url(source, limit=limit)
    try:
        import aiohttp
    except ModuleNotFoundError as exc:
        raise DougaFetchError(
            "aiohttp is required for gofile-douga fetch",
            url=api_url,
        ) from exc

    timeout = aiohttp.ClientTimeout(total=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    try:
        async with session.get(
            api_url,
            headers=DOUGA_JSON_HEADERS,
            timeout=timeout,
        ) as response:
            if response.status != 200:
                raise DougaFetchError(
                    f"gofile-douga API returned HTTP {response.status}",
                    url=api_url,
                    status=response.status,
                )
            data = await response.json(content_type=None)
    except DougaFetchError:
        raise
    except Exception as exc:
        raise DougaFetchError(
            f"gofile-douga API request failed: {exc}",
            url=api_url,
        ) from exc

    if not isinstance(data, dict):
        raise DougaFetchError(
            "gofile-douga API returned unexpected JSON payload",
            url=api_url,
        )
    return _dedupe_gofile_urls(data.get("items") or [])


async def fetch_douga_sources(
    session: aiohttp.ClientSession,
    sources: list[str] | None = None,
    limit: int = 60,
) -> dict[str, list[str]]:
    selected = list(sources) if sources else list(DOUGA_SOURCE_KEYS)
    results: dict[str, list[str]] = {}
    for source in selected:
        key = normalize_douga_source(source)
        try:
            results[key] = await fetch_douga_urls(session, key, limit=limit)
        except (DougaFetchError, ValueError):
            results[key] = []
    return results


async def check_douga_alive(session: aiohttp.ClientSession, content_id: str) -> bool:
    content_id = str(content_id).strip()
    if not content_id:
        return False

    try:
        import aiohttp
    except ModuleNotFoundError:
        return True

    page_url = f"{DOUGA_BASE}/g/{content_id}?from=new"
    timeout = aiohttp.ClientTimeout(total=ALIVE_CHECK_TIMEOUT_SECONDS)
    try:
        async with session.get(
            page_url,
            headers=DOUGA_PAGE_HEADERS,
            timeout=timeout,
        ) as response:
            if response.status != 200:
                return True
            html = await response.text()
            if "削除済み" in html:
                return False
    except Exception:
        return True
    return True
