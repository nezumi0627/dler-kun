"""Append-only JSON-lines history storage."""

import json
from pathlib import Path


class HistoryStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, record: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
