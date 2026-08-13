from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_API_BASE = "https://rwzugqnp.fun800.click/app-api"
DEFAULT_PAGE_HOST = "cdn.mvfile.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

SHORT_LINK_RE = re.compile(r"^[A-Za-z0-9_-]{4,32}$")


@dataclass(frozen=True)
class MvfileEntry:
    short_link: str
    name: str
    is_folder: bool
    page_url: str
    file_size: int | None = None
    duration: str | None = None
    thumbnail_url: str | None = None
    media_url: str | None = None
    guid: str | None = None
    channel_link: str | None = None
    children_count: int | None = None
    raw: dict[str, Any] | None = None


class MvfileApiError(RuntimeError):
    """Raised when the mvfile land-page API returns an unexpected payload."""


def extract_short_link(url: str) -> str | None:
    value = (url or "").strip()
    if not value:
        return None
    if SHORT_LINK_RE.fullmatch(value):
        return value
    parsed = urlparse(value if "://" in value else f"https://{value}")
    path = (parsed.path or "").strip("/")
    if not path:
        return None
    candidate = path.split("/")[0]
    return candidate if SHORT_LINK_RE.fullmatch(candidate) else None


def page_domain_from_url(url: str, fallback: str = DEFAULT_PAGE_HOST) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower()
    return host or fallback


def page_url_for(short_link: str, domain: str = DEFAULT_PAGE_HOST) -> str:
    return f"https://{domain}/{short_link}"


def fetch_info(
    short_link: str,
    *,
    domain: str = DEFAULT_PAGE_HOST,
    api_base: str = DEFAULT_API_BASE,
    timeout_seconds: float = 30.0,
    password: str | None = None,
) -> MvfileEntry:
    params = {
        "externalLinks": short_link,
        "domain": domain,
    }
    if password:
        # Password unlock uses a separate endpoint in the SPA; for locked
        # pages getInfo already returns status=password. Keep hook for later.
        params["password"] = password
    payload = _api_get(
        f"{api_base.rstrip('/')}/flow/land-page/getInfo",
        params,
        referer=page_url_for(short_link, domain),
        timeout_seconds=timeout_seconds,
    )
    info = ((payload.get("data") or {}).get("info") or {}) if isinstance(payload, dict) else {}
    net = info.get("netDiskInfo") or {}
    extra = info.get("extraInfo") or {}
    rules = ((payload.get("data") or {}).get("rules") or {}) if isinstance(payload, dict) else {}
    status = str(rules.get("status") or "0")
    if status == "4" or status == "5":
        raise MvfileApiError("auth_required")
    if status in {"2", "3"}:
        raise MvfileApiError("not_found")
    landing = str(net.get("landingPage") or short_link)
    is_folder = bool(net.get("isFolder"))
    media_url = _first_str(net.get("originUrl"), net.get("fileUrl"))
    return MvfileEntry(
        short_link=landing,
        name=str(net.get("name") or landing),
        is_folder=is_folder,
        page_url=page_url_for(landing, domain),
        file_size=_optional_int(net.get("fileSize")),
        duration=_optional_str(net.get("length")),
        thumbnail_url=_first_str(net.get("coverImage"), net.get("previewUrl")),
        media_url=media_url,
        guid=_optional_str(net.get("guid")),
        channel_link=_optional_str(extra.get("externalLinks")),
        children_count=_optional_int(net.get("childrenFileNum") or net.get("totalFileNum")),
        raw=payload if isinstance(payload, dict) else None,
    )


def list_entries(
    short_link: str,
    *,
    domain: str = DEFAULT_PAGE_HOST,
    api_base: str = DEFAULT_API_BASE,
    page_size: int = 50,
    sort_order: int = 2,
    timeout_seconds: float = 30.0,
    max_pages: int = 50,
) -> list[MvfileEntry]:
    results: list[MvfileEntry] = []
    page_no = 1
    total = None
    while page_no <= max_pages:
        payload = _api_get(
            f"{api_base.rstrip('/')}/flow/land-page/list_by_links_page",
            {
                "externalLinks": short_link,
                "domain": domain,
                "pageNo": page_no,
                "pageSize": page_size,
                "sortOrder": sort_order,
            },
            referer=page_url_for(short_link, domain),
            timeout_seconds=timeout_seconds,
        )
        data = (payload.get("data") or {}) if isinstance(payload, dict) else {}
        items = list(data.get("list") or [])
        if total is None:
            total = _optional_int(data.get("total")) or 0
        if not items:
            break
        for item in items:
            landing = str(item.get("landingPage") or "").strip()
            if not landing:
                continue
            results.append(
                MvfileEntry(
                    short_link=landing,
                    name=str(item.get("name") or landing),
                    is_folder=bool(item.get("isFolder")),
                    page_url=page_url_for(landing, domain),
                    file_size=_optional_int(item.get("fileSize")),
                    duration=_optional_str(item.get("length")),
                    thumbnail_url=_optional_str(item.get("coverImage")),
                    children_count=_optional_int(item.get("childrenFileNum")),
                    raw=item if isinstance(item, dict) else None,
                )
            )
        if total and len(results) >= total:
            break
        page_no += 1
    return _dedupe_by_short_link(results)


def resolve_download_targets(
    url: str,
    *,
    api_base: str = DEFAULT_API_BASE,
    timeout_seconds: float = 30.0,
    password: str | None = None,
    related: bool = False,
) -> list[MvfileEntry]:
    short_link = extract_short_link(url)
    if not short_link:
        raise MvfileApiError("invalid_request")
    domain = page_domain_from_url(url)
    root = fetch_info(
        short_link,
        domain=domain,
        api_base=api_base,
        timeout_seconds=timeout_seconds,
        password=password,
    )
    if root.is_folder:
        listing = root.short_link
    elif related and root.channel_link:
        listing = root.channel_link
    else:
        return [root]
    listed = list_entries(
        listing,
        domain=domain,
        api_base=api_base,
        timeout_seconds=timeout_seconds,
    )
    targets: list[MvfileEntry] = []
    for item in listed:
        if item.is_folder:
            continue
        detail = fetch_info(
            item.short_link,
            domain=domain,
            api_base=api_base,
            timeout_seconds=timeout_seconds,
        )
        targets.append(detail)
    return _dedupe_by_short_link(targets)


def _api_get(
    endpoint: str,
    params: dict[str, Any],
    *,
    referer: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    from urllib.parse import urlencode

    query = urlencode({k: v for k, v in params.items() if v is not None and v != ""})
    url = f"{endpoint}?{query}" if query else endpoint
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Origin": f"https://{urlparse(referer).hostname or DEFAULT_PAGE_HOST}",
            "Referer": referer,
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", "replace")
    except OSError as exc:
        raise MvfileApiError(f"network_error: {exc}") from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise MvfileApiError("network_error") from exc
    if not isinstance(payload, dict):
        raise MvfileApiError("network_error")
    code = payload.get("code")
    if code is not None and int(code) != 0:
        msg = str(payload.get("msg") or f"api code {code}")
        if "password" in msg.lower() or int(code) in {401, 403}:
            raise MvfileApiError("auth_required")
        raise MvfileApiError(msg)
    return payload


def _dedupe_by_short_link(items: list[MvfileEntry]) -> list[MvfileEntry]:
    seen: set[str] = set()
    out: list[MvfileEntry] = []
    for item in items:
        key = item.short_link
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _first_str(*values: Any) -> str | None:
    for value in values:
        text = _optional_str(value)
        if text:
            return text
    return None
