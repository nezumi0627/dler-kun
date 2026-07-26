from __future__ import annotations

import importlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO
from uuid import uuid4

from .engines.gofile.seeds import DEFAULT_GOFILE_RANKING_SEEDS
from .models import CacheEntry, CacheStatus, JobStatus, LogEvent, LogLevel, QueueJob
from .progress_ui import (
    LivePanel,
    ProgressSnapshot,
    enable_windows_ansi,
    is_interactive_tty,
    snapshot_from_state,
)

DEFAULT_85XO_SEEDS = importlib.import_module(
    "dler_kun.engines.85xo.seeds"
).DEFAULT_85XO_SEEDS


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConfigManager:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path("config.json")
        self._config = self._load()

    def _load(self) -> dict[str, Any]:
        default = {
            "output_dir": "downloads",
            "threads": 3,
            "timeout": 30,
            "retry": 2,
            "language": "ja",
            "proxy": "",
            "cookie": "",
            "user_agent": "",
            "engine_paths": {
                "twimg": os.environ.get("DLER_TWIMG_PATH", ""),
                "gofile": os.environ.get("DLER_GOFILE_PATH", ""),
                "85xo": os.environ.get("DLER_85XO_PATH", ""),
            },
            "85xo": {
                "default_seeds": list(DEFAULT_85XO_SEEDS),
                "days": 10,
                "max_pages": 50,
                "network_capture_seconds": 15.0,
            },
            "gofile": {
                "ranking_seeds": list(DEFAULT_GOFILE_RANKING_SEEDS),
                "ranking_limit": 60,
                "max_more_clicks": 5,
            },
        }
        if not self.path.exists():
            return default
        try:
            with self.path.open("r", encoding="utf-8") as file:
                user_config = json.load(file)
        except (OSError, json.JSONDecodeError):
            return default
        merged = _deep_merge(default, user_config)
        return _normalize_gofile_config(_normalize_85xo_config(merged))

    def save(self) -> None:
        _atomic_write_json(self.path, self._config)

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._config[key] = value

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        self._config = _normalize_gofile_config(
            _normalize_85xo_config(_deep_merge(self._config, values))
        )
        self.save()
        return self.as_dict()

    def as_dict(self) -> dict[str, Any]:
        return dict(self._config)


class LogManager:
    def __init__(self, max_events: int = 1000) -> None:
        self._events: list[LogEvent] = []
        self._max_events = max_events
        self._lock = threading.Lock()

    def emit(
        self,
        level: LogLevel,
        message: str,
        engine_id: str | None = None,
        job_id: str | None = None,
        **details: Any,
    ) -> LogEvent:
        event = LogEvent(level, message, engine_id, job_id, details)
        with self._lock:
            self._events.append(event)
            self._events = self._events[-self._max_events :]
        return event

    def info(self, message: str, **kwargs: Any) -> LogEvent:
        return self.emit(LogLevel.INFO, message, **kwargs)

    def success(self, message: str, **kwargs: Any) -> LogEvent:
        return self.emit(LogLevel.SUCCESS, message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> LogEvent:
        return self.emit(LogLevel.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> LogEvent:
        return self.emit(LogLevel.ERROR, message, **kwargs)

    def debug(self, message: str, **kwargs: Any) -> LogEvent:
        return self.emit(LogLevel.DEBUG, message, **kwargs)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(event) for event in self._events]


class HistoryManager:
    def __init__(self, path: Path | None = None, max_items: int = 5000) -> None:
        self.path = path or Path("history.json")
        self._max_items = max_items
        self._lock = threading.Lock()
        self._items = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return payload if isinstance(payload, list) else []

    def append(self, item: dict[str, Any]) -> None:
        with self._lock:
            self._items.append(item)
            self._items = self._items[-self._max_items :]
            _atomic_write_json(self.path, self._items)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._items)


class DownloadCacheManager:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path("download_cache.json")
        self._lock = threading.Lock()
        self._items = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(key)
            return dict(item) if item else None

    def is_complete(self, key: str) -> bool:
        item = self.get(key)
        if not item or item.get("status") != CacheStatus.COMPLETE.value:
            return False
        path = Path(str(item.get("path") or ""))
        expected_size = int(item.get("size") or 0)
        return (
            path.exists()
            and path.stat().st_size > 0
            and (expected_size <= 0 or path.stat().st_size == expected_size)
        )

    def mark(
        self,
        key: str,
        url: str,
        path: Path,
        status: CacheStatus,
        engine_id: str | None = None,
        error: str = "",
    ) -> None:
        size = path.stat().st_size if path.exists() and path.is_file() else 0
        entry = CacheEntry(
            key=key,
            url=url,
            path=str(path),
            status=status,
            size=size,
            engine_id=engine_id,
            error=error,
        )
        with self._lock:
            payload = asdict(entry)
            payload["status"] = status.value
            self._items[key] = payload
            _atomic_write_json(self.path, self._items)

    def summary(self) -> dict[str, int]:
        counts = {status.value: 0 for status in CacheStatus}
        with self._lock:
            for item in self._items.values():
                status = str(item.get("status") or "")
                if status in counts:
                    counts[status] += 1
        return counts

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._items.values())


class ProgressManager:
    """Job progress store with optional compact LivePanel rendering."""

    def __init__(
        self,
        *,
        live: bool | None = None,
        stream: TextIO | None = None,
    ) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._started_at: dict[str, float] = {}
        self._stream = stream
        self._live_enabled = is_interactive_tty(stream) if live is None else bool(live)
        self._panel: LivePanel | None = None
        if self._live_enabled:
            enable_windows_ansi()
            self._panel = LivePanel(stream=stream)

    @property
    def live_enabled(self) -> bool:
        return self._live_enabled and self._panel is not None

    def start_live(self) -> None:
        if self._panel is not None:
            self._panel.start()

    def close_live(self) -> None:
        if self._panel is not None:
            self._panel.close()

    def update(self, job_id: str, **state: Any) -> None:
        with self._lock:
            current = self._items.get(job_id, {})
            if job_id not in self._started_at:
                self._started_at[job_id] = time.perf_counter()
            current.update(state)
            current["updated_at"] = utc_now()
            self._items[job_id] = current
            snap = self._snapshot_locked(job_id, current)
        if self._panel is not None and snap is not None:
            self._panel.update(job_id, snap)

    def finish(self, job_id: str, *, ok: bool = True, **state: Any) -> None:
        with self._lock:
            current = self._items.get(job_id, {})
            if job_id not in self._started_at:
                self._started_at[job_id] = time.perf_counter()
            current.update(state)
            current["updated_at"] = utc_now()
            self._items[job_id] = current
            snap = self._snapshot_locked(job_id, current, done=True, ok=ok)
        if self._panel is not None and snap is not None:
            self._panel.finish(job_id, snap, ok=ok)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._items.get(job_id, {}))

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(value, id=key) for key, value in self._items.items()]

    def _snapshot_locked(
        self,
        job_id: str,
        state: dict[str, Any],
        *,
        done: bool = False,
        ok: bool = True,
    ) -> ProgressSnapshot | None:
        started = self._started_at.get(job_id, time.perf_counter())
        elapsed = max(0.0, time.perf_counter() - started)
        status = str(state.get("state") or "").lower()
        if status in {
            JobStatus.SUCCESS.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
            JobStatus.SKIPPED.value,
            JobStatus.UNSUPPORTED.value,
        }:
            done = True
            ok = status == JobStatus.SUCCESS.value
        return snapshot_from_state(state, elapsed=elapsed, done=done, ok=ok)


class ThreadPool:
    def __init__(self, max_workers: int) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def submit(self, fn: Callable, *args: Any, **kwargs: Any):
        return self._executor.submit(fn, *args, **kwargs)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class RetryManager:
    def __init__(self, attempts: int = 2) -> None:
        self.attempts = attempts

    def run(self, fn: Callable, *args: Any, **kwargs: Any):
        last_error: Exception | None = None
        for _ in range(max(1, self.attempts + 1)):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - normalized at caller boundary.
                last_error = exc
        raise last_error  # type: ignore[misc]


class ProxyManager:
    def __init__(self, config: ConfigManager) -> None:
        self._config = config

    def get_proxy(self) -> str:
        return str(self._config.get("proxy", "") or "")


class CookieManager:
    def __init__(self, config: ConfigManager) -> None:
        self._config = config

    def get_cookie(self) -> str:
        return str(self._config.get("cookie", "") or "")


class UpdateChecker:
    def current(self) -> dict[str, str]:
        return {"status": "not_configured"}


class QueueManager:
    def __init__(self) -> None:
        self._jobs: dict[str, QueueJob] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()

    def create(
        self, kind: str, engine_id: str, title: str, output_dir: str
    ) -> QueueJob:
        job = QueueJob(
            id=f"job-{uuid4().hex[:12]}",
            kind=kind,
            engine_id=engine_id,
            status=JobStatus.PENDING,
            title=title,
            output_dir=output_dir,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def update(self, job_id: str, **changes: Any) -> QueueJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            for key, value in changes.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            job.updated_at = utc_now()
            return job

    def cancel(self, job_id: str) -> QueueJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            self._cancelled.add(job_id)
            job.status = JobStatus.CANCELLED
            job.error = "cancelled"
            job.updated_at = utc_now()
            return job

    def cancel_all(self) -> list[QueueJob]:
        with self._lock:
            jobs = list(self._jobs.values())
            for job in jobs:
                if job.status not in {
                    JobStatus.SUCCESS,
                    JobStatus.FAILED,
                    JobStatus.SKIPPED,
                    JobStatus.UNSUPPORTED,
                    JobStatus.CANCELLED,
                }:
                    self._cancelled.add(job.id)
                    job.status = JobStatus.CANCELLED
                    job.error = "cancelled"
                    job.updated_at = utc_now()
            return jobs

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(job) for job in self._jobs.values()]


def _normalize_gofile_config(config: dict[str, Any]) -> dict[str, Any]:
    gofile = config.get("gofile")
    if not isinstance(gofile, dict):
        return config

    ranking_seeds = gofile.get("ranking_seeds")
    if isinstance(ranking_seeds, str):
        gofile["ranking_seeds"] = (
            [ranking_seeds.strip()] if ranking_seeds.strip() else []
        )
    elif isinstance(ranking_seeds, (tuple, list)):
        gofile["ranking_seeds"] = [
            str(seed).strip() for seed in ranking_seeds if str(seed).strip()
        ]
    elif not ranking_seeds:
        gofile["ranking_seeds"] = list(DEFAULT_GOFILE_RANKING_SEEDS)
    if not gofile.get("ranking_seeds"):
        gofile["ranking_seeds"] = list(DEFAULT_GOFILE_RANKING_SEEDS)

    if "ranking_limit" not in gofile:
        gofile["ranking_limit"] = 60
    if "max_more_clicks" not in gofile:
        gofile["max_more_clicks"] = 5

    config["gofile"] = gofile
    return config


def _normalize_85xo_config(config: dict[str, Any]) -> dict[str, Any]:
    config_85xo = config.get("85xo")
    if not isinstance(config_85xo, dict):
        return config

    legacy_seed = config_85xo.get("default_seed")
    if legacy_seed:
        config_85xo["default_seeds"] = [legacy_seed]
    else:
        default_seeds = config_85xo.get("default_seeds")
        if isinstance(default_seeds, str):
            config_85xo["default_seeds"] = [default_seeds]
        elif isinstance(default_seeds, (tuple, list)):
            config_85xo["default_seeds"] = [
                str(seed).strip() for seed in default_seeds if str(seed).strip()
            ]
        elif not default_seeds:
            config_85xo["default_seeds"] = list(DEFAULT_85XO_SEEDS)
    if not config_85xo.get("default_seeds"):
        config_85xo["default_seeds"] = list(DEFAULT_85XO_SEEDS)

    config_85xo.pop("default_seed", None)

    config["85xo"] = config_85xo
    return config


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)
