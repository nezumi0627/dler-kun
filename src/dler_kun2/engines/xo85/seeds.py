"""Verified listing roots and strict expansion of user-provided seeds."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

from dler_kun2.domain.errors import EngineError, ErrorCode

BASE = "https://www.85po.net/ja"
DEFAULT_SEEDS = (f"{BASE}/latest-updates/", "https://www.85po.net/vi/latest-updates/")
ALIASES = {
    "latest-updates": (f"{BASE}/latest-updates/",),
    "home": (f"{BASE}/",),
    "top-rated": (f"{BASE}/top-rated/",),
    "most-popular": (f"{BASE}/most-popular/",),
    "tags": (f"{BASE}/tags/",),
    "members": (f"{BASE}/members/",),
    "member-629": (f"{BASE}/members/629/",),
    "member-629-videos": (f"{BASE}/members/629/videos/",),
    "member-629-friends": (f"{BASE}/members/629/friends/",),
    "member-629-favorites": (f"{BASE}/members/629/favorites/videos/",),
}


def _expand(value: object) -> tuple[str, ...]:
    if not isinstance(value, str) or not value.strip():
        raise EngineError(ErrorCode.INVALID_REQUEST, "85xo source must be a known alias or verified URL")
    value = value.strip()
    alias = ALIASES.get(value.lower())
    if alias is not None:
        return alias
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise EngineError(ErrorCode.INVALID_REQUEST, "invalid 85xo source URL") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"85po.net", "www.85po.net"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not parsed.path.startswith("/")
    ):
        raise EngineError(ErrorCode.INVALID_REQUEST, "85xo source must use the verified 85po.net HTTPS host")
    return (value,)


def resolve_seeds(seeds: tuple[str, ...], options: Mapping[str, object]) -> tuple[str, ...]:
    """Expand aliases and validate all explicit inputs; never silently default them."""
    explicit: list[object] = list(seeds)
    if "sources" in options:
        configured = options["sources"]
        if isinstance(configured, str):
            explicit.append(configured)
        elif isinstance(configured, (list, tuple)):
            explicit.extend(configured)
        else:
            raise EngineError(ErrorCode.INVALID_REQUEST, "85xo sources must be a string or list")
    if not explicit:
        return DEFAULT_SEEDS
    expanded = (url for seed in explicit for url in _expand(seed))
    return tuple(dict.fromkeys(expanded))
