from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MediaItem:
    url: str
    source_page: str
    title: str | None = None
    published_at: datetime | None = None

    @property
    def display_name(self) -> str:
        return self.title or self.url.rsplit("/", 1)[-1] or "download"
