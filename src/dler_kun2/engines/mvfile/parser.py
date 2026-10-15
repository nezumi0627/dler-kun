"""Strictly parse the two fun800 API response shapes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dler_kun2.domain.errors import EngineError, ErrorCode


@dataclass(frozen=True)
class Entry:
    code: str
    name: str
    folder: bool
    media_url: str | None
    size: int | None = None
    channel: str | None = None


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EngineError(ErrorCode.NETWORK_ERROR, "malformed fun800 API object")
    return value


def _code(value: Any) -> str:
    from re import fullmatch

    if isinstance(value, str) and fullmatch(r"[A-Za-z0-9_-]{4,32}", value):
        return value
    raise EngineError(ErrorCode.NOT_FOUND, "invalid fun800 share identifier")


def unwrap(payload: Any) -> dict[str, Any]:
    body = _object(payload)
    code = body.get("code", 0)
    if str(code) not in {"0", "200"}:
        if str(code) in {"401", "403"}:
            raise EngineError(ErrorCode.AUTH_REQUIRED, "share requires authorization")
        if str(code) == "429":
            raise EngineError(ErrorCode.RATE_LIMITED, "service is rate limited")
        raise EngineError(ErrorCode.NETWORK_ERROR, "fun800 API returned an error")
    return _object(body.get("data"))


def _media_url(info: dict[str, Any]) -> str | None:
    from urllib.parse import urlsplit

    for key in ("originUrl", "fileUrl"):
        value = info.get(key)
        if not isinstance(value, str):
            continue
        if value.rstrip("/").endswith("/null"):
            continue
        parsed = urlsplit(value)
        if parsed.scheme in {"https", "http"} and parsed.hostname:
            return value
    return None


def _entry(value: Any, fallback: str | None = None, channel: str | None = None) -> Entry:
    row = _object(value)
    net = _object(row.get("netDiskInfo", row))
    code = _code(net.get("shortLink") or net.get("landingPage") or fallback)
    raw_size = net.get("fileSize")
    try:
        size = int(raw_size) if raw_size not in (None, "") else None
    except (TypeError, ValueError):
        size = None
    if size is not None and size < 0:
        size = None
    return Entry(code, str(net.get("name") or code), bool(net.get("isFolder")), _media_url(net), size, channel)


def parse_info(payload: Any, code: str) -> Entry:
    data = unwrap(payload)
    rules = data.get("rules") or {}
    if isinstance(rules, dict):
        status = str(rules.get("status", "0"))
        if status in {"4", "5"}:
            raise EngineError(ErrorCode.AUTH_REQUIRED, "share requires authorization")
        if status in {"2", "3"}:
            raise EngineError(ErrorCode.NOT_FOUND, "share not found")
    info = _object(data.get("info"))
    extra = info.get("extraInfo") or {}
    channel = extra.get("externalLinks") if isinstance(extra, dict) else None
    return _entry(info, code, channel if isinstance(channel, str) else None)


def parse_list(payload: Any) -> tuple[tuple[Entry, ...], int | None]:
    data = unwrap(payload)
    rows = data.get("list")
    if not isinstance(rows, list):
        raise EngineError(ErrorCode.NETWORK_ERROR, "fun800 list is missing")
    raw_total = data.get("total")
    try:
        total = max(0, int(raw_total)) if raw_total is not None else None
    except (TypeError, ValueError):
        total = None
    return tuple(_entry(row) for row in rows), total
