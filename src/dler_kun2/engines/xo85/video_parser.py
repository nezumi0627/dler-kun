"""Extract direct media URLs and upload dates from a video page."""

from __future__ import annotations

import json
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin

_GET_FILE = re.compile(r"https?://[^\s\"'<>]+?/get_file/[^\s\"'<>]+?\.mp4[^\s\"'<>]*", re.I)
_BR = re.compile(r"[?&]br=(\d+)")


class _MediaMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        for key in ("src", "href", "content"):
            value = attributes.get(key)
            if value:
                self.values.append(value)


def parse_media_page(html: str, page_url: str):
    parser = _MediaMarkup()
    parser.feed(html)
    candidates = set(_GET_FILE.findall(unescape(html)))
    candidates.update(urljoin(page_url, unescape(value)) for value in parser.values if "/get_file/" in value)
    candidates = {url for url in candidates if "screenshots/" not in url.lower() and ".jpg" not in url.lower()}
    if not candidates:
        return None, None
    media = max(candidates, key=lambda url: ("download=true" in url.lower(), int((_BR.search(url) or [None, "0"])[1])))
    uploaded = None
    for match in re.finditer(r'<meta\b[^>]*itemprop=["\']uploadDate["\'][^>]*content=["\']([^"\']+)', html, re.I):
        uploaded = _iso(match.group(1))
        if uploaded:
            break
    if uploaded is None:
        for raw in re.findall(r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script\s*>', html, re.I | re.S):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get("uploadDate"):
                uploaded = _iso(str(value["uploadDate"]))
                if uploaded:
                    break
    return media, uploaded


def _iso(value):
    from datetime import datetime

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
