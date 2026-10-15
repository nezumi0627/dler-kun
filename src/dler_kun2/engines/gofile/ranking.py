"""Public GoFile ranking discovery; age verification is never bypassed."""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import parse_qs, urlsplit

from dler_kun2.domain.errors import EngineError, ErrorCode

DOUGA = "https://gofile-douga.com"
LAB_PAGES = {
    "popular-24h": "https://gofilelab.com/ja/popular-24h",
    "popular-30d": "https://gofilelab.com/ja/popular-30d",
    "newest": "https://gofilelab.com/ja/newest",
    "dl-ranking": "https://gofilelab.com/ja/dl-ranking",
}
_ID = re.compile(r"https?://(?:www\.)?gofile\.io/d/([A-Za-z0-9]+)", re.I)
DOUGA_SOURCES = (
    f"{DOUGA}/new",
    f"{DOUGA}/",
    f"{DOUGA}/?sort=24h",
    f"{DOUGA}/?sort=3days",
)
LAB_SOURCES = tuple(LAB_PAGES.values())


def normalize_sources(seeds: tuple[str, ...]) -> tuple[str, ...]:
    expanded: list[str] = []
    for seed in seeds:
        key = seed.strip().lower()
        if key in {"douga", "gofile-douga"}:
            expanded.extend(DOUGA_SOURCES)
        elif key in {"lab", "gofilelab"}:
            expanded.extend(LAB_SOURCES)
        elif key == "new":
            expanded.append(DOUGA_SOURCES[0])
        elif key == "home":
            expanded.append(DOUGA_SOURCES[1])
        elif key == "24h":
            expanded.extend((DOUGA_SOURCES[2], LAB_PAGES["popular-24h"]))
        elif key == "3days":
            expanded.append(DOUGA_SOURCES[3])
        elif key in LAB_PAGES:
            expanded.append(LAB_PAGES[key])
        else:
            expanded.append(seed)
    return tuple(dict.fromkeys(expanded))


def _source(seed: str) -> tuple[str, str]:
    value = seed.strip()
    if value in LAB_PAGES:
        return "lab", value
    parsed = urlsplit(value if "://" in value else f"https://{value}")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host == "gofile-douga.com":
        if parsed.path.rstrip("/") == "/new":
            return "douga", "new"
        query = parse_qs(parsed.query)
        source = (query.get("sort") or query.get("tab") or ["home"])[0].lower()
        normalized = {"3d": "3days", "3day": "3days", "12h": "home", "24h": "24h"}.get(source, source)
        if parsed.path.rstrip("/") not in {"", "/", "/ranking"} or normalized not in {"home", "24h", "3days"}:
            raise EngineError(ErrorCode.INVALID_REQUEST, "unsupported GoFile Douga ranking source")
        return "douga", normalized
    if host == "gofilelab.com":
        key = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if key in LAB_PAGES:
            return "lab", key
        raise EngineError(ErrorCode.INVALID_REQUEST, "unsupported GoFile Lab ranking source")
    raise EngineError(ErrorCode.INVALID_REQUEST, "unsupported GoFile ranking source")


def _ranking_url(source: str, limit: int) -> str:
    if source == "new":
        return f"{DOUGA}/api/new?limit={limit}"
    tab = {"home": "12h", "24h": "24h", "3days": "3d"}[source]
    return f"{DOUGA}/api/rankings?tab={tab}&limit={limit}"


def _gofile_ids(values: Iterable[object]) -> tuple[str, ...]:
    found: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value)
        for match in _ID.finditer(text):
            content_id = match.group(1)
            if content_id not in seen:
                seen.add(content_id)
                found.append(content_id)
    return tuple(found)


async def fetch_ids(http, source_url: str, *, limit: int = 60) -> tuple[str, ...]:
    if not 1 <= limit <= 500:
        raise EngineError(ErrorCode.INVALID_REQUEST, "GoFile ranking limit must be 1..500")
    kind, source = _source(source_url)
    if kind == "douga":
        response = await http.request("GET", _ranking_url(source, limit), headers={"Accept": "application/json", "Referer": f"{DOUGA}/"})
        payload = await response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise EngineError(ErrorCode.NETWORK_ERROR, "GoFile Douga returned malformed ranking data")
        if payload.get("status") not in (None, "ok", "success"):
            raise EngineError(ErrorCode.NETWORK_ERROR, "GoFile Douga rejected the ranking request")
        return _gofile_ids(item.get("gofileUrl", "") for item in payload["items"] if isinstance(item, dict))[:limit]

    response = await http.request("GET", LAB_PAGES[source], headers={"Accept": "text/html,application/xhtml+xml"})
    html = await response.text()
    if "age-verification" in html.lower() or "18歳以上" in html:
        raise EngineError(ErrorCode.AUTH_REQUIRED, "GoFile Lab requires an explicit age-verification step")
    ids = _gofile_ids((html,))
    if not ids:
        raise EngineError(ErrorCode.NETWORK_ERROR, "GoFile Lab ranking page contains no supported share links")
    return ids[:limit]
