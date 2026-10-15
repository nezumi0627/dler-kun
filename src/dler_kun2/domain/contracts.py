"""Immutable engine inputs and the asynchronous engine interface."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from .models import CrawlResult, DownloadResult

EngineOptionValue = str | int | float | bool | None
EngineOptions = Mapping[str, EngineOptionValue]


def freeze_options(options: EngineOptions) -> EngineOptions:
    """Take an immutable snapshot at the engine boundary."""
    values = dict(options)
    for key, value in values.items():
        if not isinstance(key, str) or not (
            value is None or isinstance(value, (str, int, float, bool))
        ) or (isinstance(value, float) and not isfinite(value)):
            raise ValueError("engine options must contain JSON scalar values")
    return MappingProxyType(values)


@dataclass(frozen=True)
class DownloadRequest:
    url: str
    output_dir: Path
    options: EngineOptions = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", freeze_options(self.options))


@dataclass(frozen=True)
class CrawlRequest:
    engine_id: str
    seeds: tuple[str, ...]
    days: int | None
    download: bool
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

    async def download(self, request: DownloadRequest) -> DownloadResult: ...

    async def crawl(self, request: CrawlRequest) -> CrawlResult: ...

    async def ranking(self, request: CrawlRequest) -> CrawlResult: ...
