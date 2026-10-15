"""Immutable engine inputs and the asynchronous engine interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .models import CrawlResult
from .plans import DownloadPlan
from .types import EngineOptions, freeze_options


@dataclass(frozen=True)
class DownloadRequest:
    url: str
    options: EngineOptions = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", freeze_options(self.options))


@dataclass(frozen=True)
class CrawlRequest:
    engine_id: str
    seeds: tuple[str, ...]
    days: int | None
    options: EngineOptions = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "seeds", tuple(self.seeds))
        object.__setattr__(self, "options", freeze_options(self.options))


@dataclass(frozen=True)
class EngineCapabilities:
    download: bool = False
    crawl: bool = False
    ranking: bool = False
    metadata: bool = False
    login: bool = False


class Engine(Protocol):
    engine_id: str
    capabilities: EngineCapabilities

    async def resolve_download(self, request: DownloadRequest) -> DownloadPlan: ...

    async def crawl(self, request: CrawlRequest) -> CrawlResult: ...

    async def ranking(self, request: CrawlRequest) -> CrawlResult: ...
