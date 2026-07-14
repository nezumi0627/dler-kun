from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

CARD_RE = re.compile(
    r'<div class="thumb thumb_rel item.*?</a>\s*</div>',
    re.S,
)
HREF_RE = re.compile(r'href="(?P<href>[^"]*/v/\d+/[^"]*)"')
TITLE_RE = re.compile(r'title="(?P<title>[^"]*)"')
THUMB_RE = re.compile(r'data-(?:original|webp)="(?P<thumb>https?://[^"]+)"')
DATE_RE = re.compile(r'thumb-item-date.*?</i>\s*(?P<date>[^<]+)</div>', re.S)
DURATION_RE = re.compile(r'<div class="time"><span[^>]*></span>\s*(?P<duration>[^<]+)</div>', re.S)
GET_FILE_RE = re.compile(r'https?://[^"\'<>\s]+/get_file/[^"\'<>\s]+?\.mp4[^"\'<>\s]*')
LD_JSON_RE = re.compile(r'<script type="application/ld\+json">\s*(?P<json>{.*?})\s*</script>', re.S)
UPLOAD_DATE_RE = re.compile(r'<meta itemprop="uploadDate" content="(?P<date>[^"]+)"')
BR_RE = re.compile(r"[?&]br=(?P<br>\d+)")


@dataclass(frozen=True)
class FastListingItem:
    page_url: str
    title: str
    published_at: datetime | None
    thumbnail_url: str | None = None
    duration: str | None = None


@dataclass(frozen=True)
class FastMediaItem:
    url: str
    source_page: str
    title: str | None = None
    published_at: datetime | None = None


def crawl_fast(
    seeds: list[str],
    days: int,
    max_pages: int,
    timeout_seconds: float = 30.0,
    now: datetime | None = None,
    fetcher: Callable[[str, float], str] | None = None,
) -> list[FastMediaItem]:
    fetcher = fetcher or fetch_html
    now = now or datetime.now(timezone.utc)
    candidates = discover_listing_items(seeds, days, max_pages, timeout_seconds, now, fetcher)
    media_items: list[FastMediaItem] = []
    for index, candidate in enumerate(candidates, start=1):
        print(f"[fast-capture] {index}/{len(candidates)} {candidate.page_url}")
        try:
            video_html = fetcher(candidate.page_url, timeout_seconds)
        except OSError as exc:
            print(f"[warn] video page fetch failed: {candidate.page_url} ({exc})")
            continue
        media_url = select_best_media_url(video_html)
        if not media_url:
            print(f"[warn] media url not found: {candidate.page_url}")
            continue
        published_at = parse_video_published_at(video_html) or candidate.published_at
        media_items.append(
            FastMediaItem(
                url=media_url,
                source_page=candidate.page_url,
                title=candidate.title,
                published_at=published_at,
            )
        )
    return media_items


def discover_listing_items(
    seeds: list[str],
    days: int,
    max_pages: int,
    timeout_seconds: float,
    now: datetime,
    fetcher: Callable[[str, float], str],
) -> list[FastListingItem]:
    results: list[FastListingItem] = []
    seen_pages: set[str] = set()
    for seed in seeds:
        old_pages = 0
        for page_number in range(1, max(1, max_pages) + 1):
            page_url = listing_page_url(seed, page_number)
            print(f"[fast-scan] listing page {page_number}/{max_pages}: {page_url}")
            html = fetcher(page_url, timeout_seconds)
            items = parse_listing_items(html, page_url, now)
            within = [item for item in items if is_within_days(item.published_at, days, now)]
            for item in within:
                if item.page_url not in seen_pages:
                    seen_pages.add(item.page_url)
                    results.append(item)
            print(
                f"[fast-scan] page {page_number}: +{len(within)} within {days} days "
                f"(total {len(results)})"
            )
            dated_items = [item for item in items if item.published_at is not None]
            if items and dated_items and not within:
                old_pages += 1
                if old_pages >= 2:
                    break
            else:
                old_pages = 0
    return results


def parse_listing_items(html: str, base_url: str, now: datetime) -> list[FastListingItem]:
    items: list[FastListingItem] = []
    for card in CARD_RE.findall(html):
        href = match_group(HREF_RE, card, "href")
        if not href:
            continue
        title = unescape(match_group(TITLE_RE, card, "title") or "")
        date_text = unescape(match_group(DATE_RE, card, "date") or "")
        items.append(
            FastListingItem(
                page_url=urljoin(base_url, href),
                title=" ".join(title.split()),
                published_at=parse_published_at(date_text, now),
                thumbnail_url=match_group(THUMB_RE, card, "thumb"),
                duration=" ".join((match_group(DURATION_RE, card, "duration") or "").split())
                or None,
            )
        )
    return items


def select_best_media_url(html: str) -> str | None:
    candidates = []
    for raw in GET_FILE_RE.findall(unescape(html)):
        if "screenshots/" in raw or ".jpg" in raw.lower():
            continue
        br_match = BR_RE.search(raw)
        br = int(br_match.group("br")) if br_match else 0
        is_download = "download=true" in raw
        candidates.append((is_download, br, raw))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def parse_video_published_at(html: str) -> datetime | None:
    upload_date = match_group(UPLOAD_DATE_RE, html, "date")
    if upload_date:
        return parse_iso_datetime(upload_date)
    ld_json = match_group(LD_JSON_RE, html, "json")
    if not ld_json:
        return None
    try:
        payload = json.loads(ld_json)
    except json.JSONDecodeError:
        return None
    return parse_iso_datetime(str(payload.get("uploadDate") or ""))


def fetch_html(url: str, timeout_seconds: float) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8", "replace")


def listing_page_url(seed_url: str, page_number: int) -> str:
    if page_number <= 1:
        return seed_url
    parsed = urlparse(seed_url)
    return parsed._replace(
        path=f"{parsed.path.rstrip('/')}/{page_number}/",
        query="",
        fragment="",
    ).geturl()


def parse_published_at(text: str, now: datetime) -> datetime | None:
    try:
        from xo_dler.dates import parse_published_at as existing_parse_published_at

        return existing_parse_published_at(text, now)
    except ModuleNotFoundError:
        normalized = " ".join(text.split())
        if "今天" in normalized or "今日" in normalized:
            return now
        if "昨天" in normalized or "昨日" in normalized:
            return now - timedelta(days=1)
        day_match = re.search(r"(?P<days>\d+)\s*(?:天前|日前|days?\s+ago)", normalized, re.I)
        if day_match:
            return now - timedelta(days=int(day_match.group("days")))
        week_match = re.search(
            r"(?P<weeks>\d+)\s*(?:星期前|週間前|weeks?\s+ago)",
            normalized,
            re.I,
        )
        if week_match:
            return now - timedelta(weeks=int(week_match.group("weeks")))
        return None


def is_within_days(value: datetime | None, days: int, now: datetime) -> bool:
    try:
        from xo_dler.dates import is_within_days as existing_is_within_days

        return existing_is_within_days(value, days, now)
    except ModuleNotFoundError:
        if value is None:
            return False
        if value.tzinfo is None and now.tzinfo is not None:
            value = value.replace(tzinfo=now.tzinfo)
        return now - timedelta(days=days) <= value <= now + timedelta(minutes=5)


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def to_existing_media_items(items: Iterable[FastMediaItem], project_path: Path):
    lib_path = str(project_path / "lib")
    import sys

    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)
    from xo_dler.models import MediaItem

    return [
        MediaItem(
            url=item.url,
            source_page=item.source_page,
            title=item.title,
            published_at=item.published_at,
        )
        for item in items
    ]


def match_group(pattern: re.Pattern[str], text: str, group: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return match.group(group).strip()
