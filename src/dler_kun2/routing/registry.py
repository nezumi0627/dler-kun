"""Reject unsafe route declarations and resolve explicit registrations."""

from __future__ import annotations

from urllib.parse import urlsplit

from dler_kun2.domain.contracts import Engine
from dler_kun2.domain.errors import EngineError, ErrorCode

from .rules import PathPrefix, RouteRule

# Legacy aliases not yet verified against a representative share page/API fixture.
# This is a quarantine list, not an engine ownership declaration.
UNVERIFIED_HOSTS = frozenset({
    "gofilelab.com", "gofile.run", "85xo.com", "85po.com",
    "mvfile.com", "file-photo.com", "tweetfile.com", "gofile.website",
    "image-share.cc", "tweetplay.com", "imagedist.com", "gofile.rocks",
    "gofile.host", "gofile.guru", "gofile.name", "mediasplayer.com",
    "twimg-media.com", "media-twimg.com", "twimg.jp", "video.twimg.jp",
    "video.twimg-image.com", "video.twimg1.com", "cdn.twimg1.com",
    "twimg1.com", "twimg-album.com", "file-bio.com", "twfiles.com",
    "gofile.video", "gofile.trade", "gofile.bar", "gofile.pl",
    "cdn1.twimg-media.com", "video.twimg.news", "video.twimg.it.com",
    "l2e.click",
})


class RouteError(Exception):
    def __init__(self, error: EngineError):
        self.error = error
        super().__init__(error.message)


class EngineRegistry:
    def __init__(self) -> None:
        self._engines: dict[str, Engine] = {}
        self._routes: list[RouteRule] = []
        self.http_runtime = None

    def register(self, engine: Engine, routes: list[RouteRule] | tuple[RouteRule, ...]) -> None:
        if engine.engine_id in self._engines:
            raise ValueError(f"engine already registered: {engine.engine_id}")
        incoming = tuple(routes)
        if any(route.engine_id != engine.engine_id for route in incoming):
            raise ValueError("route engine id mismatch")
        for index, route in enumerate(incoming):
            for existing in (*self._routes, *incoming[:index]):
                if set(route.hosts).isdisjoint(existing.hosts):
                    continue
                left, right = route.path_predicate, existing.path_predicate
                if not (isinstance(left, PathPrefix) and isinstance(right, PathPrefix) and left.disjoint(right)):
                    raise ValueError("overlapping routes need provably disjoint paths")
        self._engines[engine.engine_id] = engine
        self._routes.extend(incoming)

    def get(self, engine_id: str) -> Engine:
        try:
            return self._engines[engine_id]
        except KeyError as exc:
            raise RouteError(EngineError(ErrorCode.UNSUPPORTED_SERVICE, "engine is pending migration")) from exc

    def sites(self) -> list[dict[str, object]]:
        return [
            {"engine_id": engine_id, "hosts": sorted({host for route in self._routes if route.engine_id == engine_id for host in route.hosts}), "capabilities": vars(engine.capabilities)}
            for engine_id, engine in sorted(self._engines.items())
        ]

    def resolve(self, url: str) -> Engine:
        try:
            parsed = urlsplit(url)
            host = parsed.hostname
            _ = parsed.port
        except ValueError as exc:
            raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "invalid URL")) from exc
        if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password or any(char.isspace() for char in url):
            raise RouteError(EngineError(ErrorCode.INVALID_REQUEST, "invalid URL"))
        host = host.lower().rstrip(".")
        candidates = [route for route in self._routes if host in route.hosts]
        quarantined = any(host == alias or host.endswith(f".{alias}") for alias in UNVERIFIED_HOSTS)
        if quarantined and (not candidates or any(route.backend_probe is None for route in candidates)):
            raise RouteError(EngineError(ErrorCode.AMBIGUOUS_SERVICE, "backend ownership is unverified"))
        matches = []
        for route in candidates:
            try:
                path_matches = route.path_predicate is None or route.path_predicate(parsed.path or "/")
            except Exception as exc:
                raise RouteError(EngineError(ErrorCode.AMBIGUOUS_SERVICE, "route path check failed")) from exc
            if not path_matches:
                continue
            try:
                probe_matches = route.backend_probe is None or route.backend_probe(url)
            except Exception as exc:
                raise RouteError(EngineError(ErrorCode.NETWORK_ERROR, "backend probe failed")) from exc
            if probe_matches:
                matches.append(route)
        if len(matches) == 1:
            return self._engines[matches[0].engine_id]
        if candidates:
            raise RouteError(EngineError(ErrorCode.AMBIGUOUS_SERVICE, "route requires explicit backend evidence"))
        raise RouteError(EngineError(ErrorCode.UNSUPPORTED_SERVICE, "no engine registered for this host"))
