from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .models import JobStatus, LogEvent, LogLevel, QueueJob


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
            "proxy": "",
            "cookie": "",
            "user_agent": "",
            "engine_paths": {
                "dl": os.environ.get("DLER_DL_PATH", ""),
                "gofile": os.environ.get("DLER_GOFILE_PATH", ""),
                "85xo": os.environ.get("DLER_85XO_PATH", ""),
            },
            "85xo": {
                "default_seed": "https://www.85xo.com/latest-updates/",
                "days": 10,
                "max_pages": 50,
                "network_capture_seconds": 15.0,
            },
        }
        if not self.path.exists():
            return default
        try:
            with self.path.open("r", encoding="utf-8") as file:
                user_config = json.load(file)
        except (OSError, json.JSONDecodeError):
            return default
        return _deep_merge(default, user_config)

    def save(self) -> None:
        _atomic_write_json(self.path, self._config)

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._config[key] = value

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


class ProgressManager:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def update(self, job_id: str, **state: Any) -> None:
        with self._lock:
            current = self._items.get(job_id, {})
            current.update(state)
            current["updated_at"] = utc_now()
            self._items[job_id] = current

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._items.get(job_id, {}))

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(value, id=key) for key, value in self._items.items()]


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
        self._lock = threading.Lock()

    def create(self, kind: str, engine_id: str, title: str, output_dir: str) -> QueueJob:
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

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(job) for job in self._jobs.values()]


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
