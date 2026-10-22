"""Read, merge, redact, and atomically save user configuration."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from dler_kun2.domain.errors import EngineError, ErrorCode

_DEFAULTS: dict[str, Any] = {
    "output_dir": "downloads",
    "threads": 3,
    "timeout": 30,
    "experimental_fallback": True,
    "retry": 2,
    "language": "ja",
    "proxy": "",
    "cookie": "",
    "user_agent": "",
    "local_addr": "",
    "engine_paths": {"twimg": ""},
    "85xo": {"days": 10, "max_pages": 50, "network_capture_seconds": 15.0},
    "gofile": {"ranking_limit": 60, "max_more_clicks": 5, "ranking_seeds": []},
    "mvfile": {"api_base": "https://rwzugqnp.fun800.click/app-api", "timeout_seconds": 30.0},
}
_SECRET_PARTS = ("cookie", "token", "password", "secret", "apikey", "authorization")


def _merge(default: dict[str, Any], supplied: dict[str, Any]) -> dict[str, Any]:
    result = dict(default)
    for key, value in supplied.items():
        if isinstance(value, dict) and isinstance(default.get(key), dict):
            result[key] = _merge(default[key], value)
        else:
            result[key] = value
    return result


def _redact(value: Any, key: str = "") -> Any:
    lowered = key.lower().replace("-", "_")
    compact = lowered.replace("_", "")
    if any(secret in compact for secret in _SECRET_PARTS):
        return "[REDACTED]" if value else value
    if isinstance(value, dict):
        return {name: _redact(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if lowered == "proxy" and value:
        return "[REDACTED]"
    return value


class ConfigStore:
    def __init__(self, path: str | Path = "config.json"):
        self.path = Path(path)
        self._config = dict(_DEFAULTS)
        if self.path.exists():
            try:
                supplied = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise EngineError(ErrorCode.INVALID_REQUEST, "configuration file is unreadable or invalid") from exc
            if not isinstance(supplied, dict):
                raise EngineError(ErrorCode.INVALID_REQUEST, "configuration root must be a JSON object")
            self._config = _merge(_DEFAULTS, supplied)

    def as_dict(self, *, redact: bool = True) -> dict[str, Any]:
        value = json.loads(json.dumps(self._config))
        return _redact(value) if redact else value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(self._config, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
