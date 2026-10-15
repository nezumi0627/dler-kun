"""Parse Videy's current public player contract."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

_VIDEO_ID = re.compile(r"[A-Za-z0-9]{8,9}\Z")
_ALIAS_PATH = re.compile(r"/([A-Za-z0-9]{8,9})\.mp4\Z", re.I)


class _VideoSourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "source":
            source = dict(attrs).get("src")
            if source:
                self.sources.append(source)


def parse_player(page_url: str, html: str, bundle_excerpt: str) -> tuple[str, str, str]:
    """Resolve `/v?id=...` using the public player's observed extension rule."""
    del bundle_excerpt  # the current app resolves the canonical player from URL query state
    try:
        parsed = urlsplit(page_url)
    except ValueError as exc:
        raise ValueError("invalid Videy video id") from exc
    if parsed.hostname in {"video.twimg.it.com", "www.video.twimg.it.com"}:
        match = _ALIAS_PATH.fullmatch(parsed.path)
        if not match or not _VIDEO_ID.fullmatch(match.group(1)):
            raise ValueError("invalid Videy mirror video id")
        video_id = match.group(1)
        extension = "mov" if len(video_id) == 9 and video_id.endswith("2") else "mp4"
        source_parser = _VideoSourceParser()
        source_parser.feed(html)
        for candidate in source_parser.sources:
            try:
                media = urlsplit(candidate)
            except ValueError:
                continue
            if media.scheme == "https" and media.hostname == "cdn.videy.co" and media.path == f"/{video_id}.{extension}":
                return video_id, candidate, extension
        raise ValueError("Videy mirror page did not expose a matching CDN media source")
    if parsed.hostname not in {"videy.co", "www.videy.co"} or parsed.path.rstrip("/") != "/v":
        raise ValueError("invalid Videy video id")
    video_id = parse_qs(parsed.query).get("id", [""])[0]
    if not _VIDEO_ID.fullmatch(video_id):
        raise ValueError("invalid Videy video id")
    extension = "mov" if len(video_id) == 9 and video_id.endswith("2") else "mp4"
    return video_id, f"https://cdn.videy.co/{video_id}.{extension}", extension
