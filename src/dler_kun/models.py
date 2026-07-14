from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNSUPPORTED = "unsupported"


class LogLevel(str, Enum):
    INFO = "INFO"
    DEBUG = "DEBUG"
    WARNING = "WARNING"
    ERROR = "ERROR"
    SUCCESS = "SUCCESS"


@dataclass(frozen=True)
class EngineCapability:
    download: bool = True
    crawl: bool = False
    ranking: bool = False
    metadata: bool = False
    login: bool = False


@dataclass(frozen=True)
class DownloadRequest:
    url: str
    output_dir: Path
    job_id: str = field(default_factory=lambda: str(uuid4()))
    engine_id: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CrawlRequest:
    service: str
    output_dir: Path
    job_id: str = field(default_factory=lambda: str(uuid4()))
    seeds: list[str] = field(default_factory=list)
    days: int = 10
    download: bool = False
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class DownloadResult:
    job_id: str
    engine_id: str
    status: JobStatus
    message: str = ""
    files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CrawlItem:
    url: str
    title: str = ""
    author: str = ""
    published_at: str | None = None
    thumbnail_url: str | None = None
    size: int | None = None
    duration: str | None = None
    downloadable: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CrawlResult:
    job_id: str
    engine_id: str
    status: JobStatus
    message: str = ""
    items: list[CrawlItem] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LogEvent:
    level: LogLevel
    message: str
    engine_id: str | None = None
    job_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class QueueJob:
    id: str
    kind: str
    engine_id: str
    status: JobStatus
    title: str
    created_at: str
    updated_at: str
    progress: float = 0.0
    speed: str = ""
    eta: str = ""
    output_dir: str = ""
    error: str = ""
