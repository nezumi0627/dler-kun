"""Small JSON cache stored atomically on disk."""

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any


class JsonCache:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = RLock()

    def read(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return {}
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            return value if isinstance(value, dict) else {}

    def write(self, value: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    json.dump(value, stream, ensure_ascii=False, allow_nan=False)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            except BaseException:
                Path(temporary).unlink(missing_ok=True)
                raise

    def get(self, key: str) -> dict[str, Any] | None:
        value = self.read().get(key)
        return dict(value) if isinstance(value, dict) else None

    def set(self, key: str, entry: dict[str, Any]) -> None:
        with self._lock:
            value = self.read()
            value[key] = dict(entry)
            self.write(value)
