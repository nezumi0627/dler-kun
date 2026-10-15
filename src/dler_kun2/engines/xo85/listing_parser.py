"""DOM-based parser for legacy cards and current 85po listing anchors."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .dates import parse_date

_VIDEO_PATH = re.compile(r"/(?:v|video)/(\d+)(?:\.html)?(?:/|$)", re.I)


@dataclass(frozen=True)
class ListingItem:
    page_url: str
    video_id: str
    title: str
    published_at: datetime | None
    thumbnail_url: str | None = None
    duration: str | None = None


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

    def content(self) -> str:
        return " ".join([*self.text, *(child.content() for child in self.children)]).strip()


class _TreeParser(HTMLParser):
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, {key.lower(): value or "" for key, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self._VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].text.append(data)


def parse_listing(html: str, base_url: str, now: datetime) -> tuple[ListingItem, ...]:
    parser = _TreeParser()
    parser.feed(html)
    parser.close()
    results: list[ListingItem] = []
    seen: set[str] = set()
    anchors = [node for node in parser.root.walk() if node.tag == "a"]
    def priority(anchor: _Node) -> int:
        parent = anchor.parent
        while parent is not None:
            classes = set(parent.attrs.get("class", "").lower().split())
            if classes.intersection({"item", "thumb_rel", "thumb", "video-item", "list-item"}):
                return 0
            parent = parent.parent
        return 1
    anchors.sort(key=priority)
    if any(priority(anchor) == 0 and _VIDEO_PATH.search(urlsplit(urljoin(base_url, anchor.attrs.get("href", ""))).path) for anchor in anchors):
        anchors = [anchor for anchor in anchors if priority(anchor) == 0]
    for anchor in anchors:
        href = anchor.attrs.get("href", "")
        match = _VIDEO_PATH.search(urlsplit(urljoin(base_url, href)).path)
        if not match:
            continue
        if match.group(1) in seen:
            existing_index = next((index for index, item in enumerate(results) if item.video_id == match.group(1)), None)
            if existing_index is not None and priority(anchor) == 0 and results[existing_index].published_at is None:
                del results[existing_index]
            else:
                continue
        seen.add(match.group(1))
        descendants = list(anchor.walk())
        title = anchor.attrs.get("title", "").strip()
        date_text = ""
        thumbnail = None
        duration = None
        for node in descendants:
            classes = set(node.attrs.get("class", "").lower().split())
            if not title and classes.intersection({"title", "card-title"}):
                title = node.content()
            if not date_text and classes.intersection({"added", "tools-text", "thumb-item-date", "date"}):
                date_text = node.content()
            if not thumbnail and node.tag == "img":
                raw_thumbnail = next((node.attrs[key] for key in ("data-original", "data-webp", "src") if node.attrs.get(key)), None)
                thumbnail = urljoin(base_url, raw_thumbnail) if raw_thumbnail else None
            if not duration and "duration" in classes:
                duration = node.content()
        canonical = urljoin(base_url, href)
        results.append(ListingItem(canonical, match.group(1), " ".join(title.split()), parse_date(date_text, now), thumbnail, duration))
    return tuple(results)
