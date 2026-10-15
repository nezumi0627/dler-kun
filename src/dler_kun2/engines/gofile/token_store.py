"""Small per-user store for one reusable guest token."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from dler_kun2.infrastructure.state.paths import state_dir


class GuestTokenStore:
    def __init__(self, path: Path | None = None):
        self.path = path or state_dir() / "gofile-guest-token.json"

    def load(self) -> str | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        token = data.get("token") if isinstance(data, dict) else None
        return token if isinstance(token, str) and token else None

    def save(self, token: str) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = self.load()
        if existing:
            return existing
        descriptor, temporary = tempfile.mkstemp(prefix=".gofile-token-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"token": token}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            try:
                os.link(temporary, self.path)
            except FileExistsError:
                pass
            return self.load() or token
        finally:
            Path(temporary).unlink(missing_ok=True)
