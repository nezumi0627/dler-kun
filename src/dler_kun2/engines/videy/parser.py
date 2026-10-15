"""Parse Videy's current public player contract."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

_VIDEO_ID = re.compile(r"[A-Za-z0-9]{8,9}\Z")


def parse_player(page_url: str, html: str, bundle_excerpt: str) -> tuple[str, str, str]:
    """Resolve `/v?id=...` using the public player's observed extension rule."""
    del html, bundle_excerpt  # the current app resolves its player from URL query state
    try:
        parsed = urlsplit(page_url)
    except ValueError as exc:
        raise ValueError("invalid Videy video id") from exc
    if parsed.hostname not in {"videy.co", "www.videy.co"} or parsed.path.rstrip("/") != "/v":
        raise ValueError("invalid Videy video id")
    video_id = parse_qs(parsed.query).get("id", [""])[0]
    if not _VIDEO_ID.fullmatch(video_id):
        raise ValueError("invalid Videy video id")
    extension = "mov" if len(video_id) == 9 and video_id.endswith("2") else "mp4"
    return video_id, f"https://cdn.videy.co/{video_id}.{extension}", extension
