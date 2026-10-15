"""Small JSON cache stored atomically on disk."""

import json
import os
from pathlib import Path
from typing import Any


class JsonCache:
    def __init__(self, path: Path):
        self.path = Path(path)

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}

    def write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".part")
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.path)
