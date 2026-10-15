"""Validate GoFile content API responses and normalize file/folder entries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from dler_kun2.domain.errors import EngineError, ErrorCode


@dataclass(frozen=True)
class ContentItem:
    item_id: str
    name: str
    kind: str
    media_url: str | None
    size: int | None
    password: str | None = None


def content_id(url: str) -> str:
    try:
        parsed = urlsplit(url)
        parsed.port
    except ValueError as exc:
        raise EngineError(ErrorCode.INVALID_REQUEST, "invalid GoFile URL") from exc
    if parsed.scheme not in {"https", "http"} or parsed.hostname not in {"gofile.io", "www.gofile.io"} or parsed.username or parsed.password:
        raise EngineError(ErrorCode.INVALID_REQUEST, "unsupported GoFile URL")
    match = re.fullmatch(r"/d/([A-Za-z0-9]+)(?:/.*)?", parsed.path)
    if not match:
        raise EngineError(ErrorCode.INVALID_REQUEST, "GoFile URL must contain a content ID")
    return match.group(1)


def parse_content(payload: Any) -> tuple[ContentItem, ...]:
    if not isinstance(payload, dict):
        raise EngineError(ErrorCode.NETWORK_ERROR, "malformed GoFile API response")
    status = str(payload.get("status", ""))
    raw_errors = payload.get("errors", [])
    has_rate_error = isinstance(raw_errors, (list, tuple, set, str)) and "error-rateLimit" in raw_errors
    if status == "error-rateLimit" or has_rate_error:
        raise EngineError(ErrorCode.RATE_LIMITED, "GoFile rate limit reached")
    if status == "error-notFound":
        raise EngineError(ErrorCode.NOT_FOUND, "GoFile content was not found")
    if status in {"error-notPremium", "error-notAuthenticated", "error-wrongToken", "error-passwordRequired", "error-wrongPassword"}:
        raise EngineError(ErrorCode.AUTH_REQUIRED, "GoFile authorization or password is required")
    if status != "ok" or not isinstance(payload.get("data"), dict):
        raise EngineError(ErrorCode.NETWORK_ERROR, "GoFile API returned an unsuccessful response")
    data = payload["data"]
    if data.get("type") == "file":
        rows = [data]
    elif isinstance(data.get("children", {}), dict):
        rows = list(data["children"].values())
    else:
        raise EngineError(ErrorCode.NETWORK_ERROR, "GoFile child list is malformed")
    items: list[ContentItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = row.get("id")
        name = row.get("name")
        kind = str(row.get("type") or "file").lower()
        if not isinstance(item_id, (str, int)) or not str(item_id):
            continue
        if not isinstance(name, str) or not name:
            name = str(item_id)
        url = row.get("link") or row.get("url")
        media = None
        if isinstance(url, str):
            parsed = urlsplit(url)
            if parsed.scheme == "https" and parsed.hostname:
                media = url
        try:
            size = int(row["size"]) if row.get("size") is not None else None
            if size is not None and size < 0:
                size = None
        except (TypeError, ValueError):
            size = None
        items.append(ContentItem(str(item_id), name, kind, media, size))
    return tuple(items)
