"""Resolve player iframes from legacy and current post markup."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urlsplit

_PROVIDERS = {"luluvdo.com", "luluvido.com", "playmogo.com"}


class _IframeParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "iframe":
            src = dict(attrs).get("src")
            if src:
                self.urls.append(src)


def extract_embed_url(html: str) -> str | None:
    parser = _IframeParser()
    parser.feed(html)
    for url in parser.urls:
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        host = (parsed.hostname or "").lower()
        if parsed.scheme in {"https", "http"} and any(host == domain or host.endswith("." + domain) for domain in _PROVIDERS):
            return url
    return None
