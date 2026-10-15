"""Parse legacy mixi-xxx and current jav-mixi WordPress listings."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

_SKIP = {"page", "category", "tag", "author", "feed", "wp-content", "wp-json"}


@dataclass(frozen=True)
class VideoPage:
    url: str
    title: str


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str]
    parent: _Node | None = None
    children: list[_Node] = field(default_factory=list)
    text: list[str] = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def text_content(self) -> str:
        return " ".join([*self.text, *(node.text_content() for node in self.children)]).strip()


class _Parser(HTMLParser):
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, {key.lower(): value or "" for key, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self._VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].text.append(data)


def parse_listing(html: str, base_url: str) -> tuple[VideoPage, ...]:
    parsed_base = urlsplit(base_url)
    host = (parsed_base.hostname or "").lower()
    parser = _Parser()
    parser.feed(html)
    parser.close()
    result: list[VideoPage] = []
    seen: set[str] = set()
    for node in parser.root.walk():
        if node.tag != "a" or not node.attrs.get("href"):
            continue
        url = urljoin(base_url, node.attrs["href"])
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname != host:
            continue
        path = parsed.path.strip("/")
        if not path or "/" in path or path.split("-")[0].lower() in _SKIP or re.fullmatch(r"\d{4}", path):
            continue
        if path in seen:
            continue
        seen.add(path)
        title = node.attrs.get("title", "").strip()
        if not title:
            title = next((child.text_content() for child in node.walk() if child.attrs.get("class", "").lower().find("title") >= 0), "")
        title = " ".join((title or node.text_content() or path).split())
        result.append(VideoPage(url, title))
    return tuple(result)


def listing_page_url(seed: str, page: int) -> str:
    if page <= 1:
        return seed
    parsed = urlsplit(seed)
    path = re.sub(r"/page/\d+/?$", "", parsed.path.rstrip("/"))
    return parsed._replace(path=f"{path}/page/{page}/", query="", fragment="").geturl()
