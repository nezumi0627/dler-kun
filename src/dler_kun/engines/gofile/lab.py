"""gofilelab.com ranking helpers (plain HTTP, no browser).

Fetches ranking HTML with age-gate cookies and extracts ``gofile.io/d/<id>``
URLs. ``max_more_clicks`` is accepted for API compatibility but unused — the
server-rendered page already contains the listing links.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    import aiohttp

LAB_PAGES: dict[str, str] = {
    "popular-24h": "https://gofilelab.com/ja/popular-24h",
    "popular-30d": "https://gofilelab.com/ja/popular-30d",
    "newest": "https://gofilelab.com/ja/newest",
    "dl-ranking": "https://gofilelab.com/ja/dl-ranking",
}

LAB_SOURCE_KEYS = ("popular-24h", "popular-30d", "newest", "dl-ranking")

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)

_GF_ID_RE = re.compile(r"gofile\.io/d/([A-Za-z0-9]+)")

_AGE_COOKIES = {
    "age_verified": "true",
    "ageVerified": "1",
    "age_confirmed": "true",
}

DEFAULT_REQUEST_TIMEOUT_SECONDS = 15.0


class LabFetchError(Exception):
    """Raised when a gofilelab HTML request fails."""

    def __init__(self, message: str, *, url: str, status: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status = status


def parse_lab_seed(seed: str) -> str | None:
    """Map seed URL or source key to a LAB source key."""
    cleaned = str(seed).strip()
    if not cleaned:
        return None

    if cleaned in LAB_PAGES:
        return cleaned

    normalized = cleaned.rstrip("/")
    for key, url in LAB_PAGES.items():
        if normalized == url.rstrip("/"):
            return key

    path = urlparse(cleaned).path.rstrip("/")
    for key in LAB_SOURCE_KEYS:
        if path == f"/ja/{key}" or path.endswith(f"/{key}"):
            return key

    return None


def _normalize_gofile_url(content_id: str) -> str:
    return f"https://gofile.io/d/{content_id}"


def _extract_urls(content: str, seen: set[str] | None = None) -> list[str]:
    urls: list[str] = []
    local_seen = seen if seen is not None else set()
    for match in _GF_ID_RE.finditer(content):
        url = _normalize_gofile_url(match.group(1))
        if url not in local_seen:
            local_seen.add(url)
            urls.append(url)
    return urls


def _lab_headers(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ja,en-US;q=0.9",
        "Referer": "https://gofilelab.com/ja/",
    }


async def _fetch_html(
    session: aiohttp.ClientSession,
    page_url: str,
    *,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> str:
    import aiohttp

    try:
        async with session.get(
            page_url,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as response:
            text = await response.text()
            if response.status >= 400:
                raise LabFetchError(
                    f"gofilelab HTTP {response.status}",
                    url=page_url,
                    status=response.status,
                )
            return text
    except LabFetchError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LabFetchError(f"gofilelab request failed: {exc}", url=page_url) from exc


async def scrape_lab_page(
    page_url: str,
    *,
    max_more_clicks: int = 5,
    user_agent: str | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> list[str]:
    """Fetch one gofilelab.com page and return deduplicated GoFile URLs."""
    del max_more_clicks  # retained for call-site compatibility
    try:
        import aiohttp
    except ImportError as exc:
        raise ModuleNotFoundError("aiohttp is required for gofilelab scraping") from exc

    ua = user_agent or _DEFAULT_USER_AGENT
    async with aiohttp.ClientSession(
        cookies=_AGE_COOKIES,
        headers=_lab_headers(ua),
    ) as session:
        html = await _fetch_html(session, page_url, timeout=timeout)
        return _extract_urls(html)


async def scrape_lab_sources(
    sources: list[str] | None = None,
    *,
    max_more_clicks: int = 5,
    user_agent: str | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, list[str]]:
    """Fetch selected gofilelab.com ranking pages over HTTP."""
    del max_more_clicks  # retained for call-site compatibility
    selected: list[str] = []
    if sources is None:
        selected = list(LAB_SOURCE_KEYS)
    else:
        # Empty list means "scrape nothing" (distinct from None = all pages).
        for source in sources:
            key = parse_lab_seed(source) or source.strip()
            if key in LAB_PAGES and key not in selected:
                selected.append(key)

    results: dict[str, list[str]] = {key: [] for key in selected}
    if not selected:
        return results

    try:
        import aiohttp
    except ImportError as exc:
        raise ModuleNotFoundError("aiohttp is required for gofilelab scraping") from exc

    ua = user_agent or _DEFAULT_USER_AGENT
    async with aiohttp.ClientSession(
        cookies=_AGE_COOKIES,
        headers=_lab_headers(ua),
    ) as session:
        global_seen: set[str] = set()
        for key in selected:
            html = await _fetch_html(session, LAB_PAGES[key], timeout=timeout)
            deduped: list[str] = []
            for url in _extract_urls(html):
                if url not in global_seen:
                    global_seen.add(url)
                    deduped.append(url)
            results[key] = deduped

    return results
