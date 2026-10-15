"""Route declarations and provably disjoint path prefixes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class PathPrefix:
    prefix: str

    def __post_init__(self) -> None:
        if not self.prefix.startswith("/"):
            raise ValueError("path prefix must start with /")

    def __call__(self, path: str) -> bool:
        return path.startswith(self.prefix)

    def disjoint(self, other: PathPrefix) -> bool:
        return not (self.prefix.startswith(other.prefix) or other.prefix.startswith(self.prefix))


@dataclass(frozen=True)
class RouteRule:
    engine_id: str
    hosts: tuple[str, ...]
    path_predicate: Callable[[str], bool] | None = None
    backend_probe: Callable[[str], bool] | None = None

    def __post_init__(self) -> None:
        hosts = tuple(host.lower().rstrip(".") for host in self.hosts)
        if not self.engine_id or not hosts or any(not host or "/" in host or ":" in host for host in hosts):
            raise ValueError("route needs an engine and valid hosts")
        object.__setattr__(self, "hosts", hosts)
