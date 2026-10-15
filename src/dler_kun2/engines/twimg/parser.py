"""Conservative parsing helpers for untrusted Twimg input URLs."""

from __future__ import annotations

import re
from urllib.parse import urlsplit


def suggested_filename(url: str) -> str:
    parsed = urlsplit(url)
    name = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or "twimg-media.mp4"
