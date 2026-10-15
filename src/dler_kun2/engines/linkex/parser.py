"""Validate Linkex share and paginated content response envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from dler_kun2.domain.errors import EngineError, ErrorCode


@dataclass(frozen=True)
class ShareItem:
    item_id: str
    name: str
    kind: str
    media_url: str | None
    parent_id: str | None = None


@dataclass(frozen=True)
class SharePage:
    items: tuple[ShareItem, ...]
    total: int | None
    has_more: bool | None


def parse_envelope(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise EngineError(ErrorCode.NETWORK_ERROR, "malformed Linkex API response")
    try:
        code = int(payload.get("code", 0))
    except (TypeError, ValueError) as exc:
        raise EngineError(ErrorCode.NETWORK_ERROR, "malformed Linkex API status") from exc
    if code in {401, 403}:
        raise EngineError(ErrorCode.AUTH_REQUIRED, "Linkex share requires authorization")
    if code == 429:
        raise EngineError(ErrorCode.RATE_LIMITED, "Linkex rate limit reached")
    if code != 0:
        message = str(payload.get("message") or payload.get("msg") or "").lower()
        error = ErrorCode.NOT_FOUND if any(word in message for word in ("not found", "expired", "invalid share")) else ErrorCode.NETWORK_ERROR
        raise EngineError(error, "Linkex API returned an error")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise EngineError(ErrorCode.NETWORK_ERROR, "Linkex API data is missing")
    return data


def parse_item(value: Any) -> ShareItem:
    if not isinstance(value, dict):
        raise EngineError(ErrorCode.NETWORK_ERROR, "malformed Linkex item")
    item_id = value.get("id")
    if not isinstance(item_id, (str, int)) or not str(item_id):
        raise EngineError(ErrorCode.NETWORK_ERROR, "Linkex item identifier is missing")
    kind = str(value.get("type") or "file").lower()
    raw_url = value.get("url") or value.get("download_url")
    media = None
    if isinstance(raw_url, str) and raw_url:
        parsed = urlsplit(raw_url)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            media = raw_url
    return ShareItem(str(item_id), str(value.get("name") or item_id), kind, media, str(value["parent_id"]) if value.get("parent_id") is not None else None)


def parse_page(payload: Any) -> SharePage:
    data = parse_envelope(payload)
    raw_items = data.get("list", data.get("items", []))
    if not isinstance(raw_items, list):
        raise EngineError(ErrorCode.NETWORK_ERROR, "Linkex item list is malformed")
    try:
        total = max(0, int(data["total"])) if data.get("total") is not None else None
    except (TypeError, ValueError):
        total = None
    has_more = data.get("has_more", data.get("hasMore"))
    return SharePage(tuple(parse_item(item) for item in raw_items), total, has_more if isinstance(has_more, bool) else None)
