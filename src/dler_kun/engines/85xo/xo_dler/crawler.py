from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from time import sleep

from .dates import is_within_days
from .models import MediaItem
from .network_media import (
    NetworkCaptureConfig,
    capture_media_items,
    capture_video_ids,
    is_video_page_url,
    video_page_url,
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class CrawlConfig:
    seeds: list[str]
    days: int = 10
    max_pages: int = 50
    max_depth: int = 2
    delay_seconds: float = 1.0
    timeout_seconds: float = 30.0
    include_undated: bool = False
    user_agent: str = DEFAULT_USER_AGENT
    headers: dict[str, str] = field(default_factory=dict)
    network_capture_seconds: float = 15.0
    browser_path: str | None = None


def crawl_once(config: CrawlConfig, now: datetime | None = None) -> list[MediaItem]:
    video_pages = discover_video_pages(config)
    print(f"[scan] video pages: {len(video_pages)}")
    found: list[MediaItem] = []

    for index, page_url in enumerate(video_pages, start=1):
        print(f"[capture] {index}/{len(video_pages)} {page_url}")
        items = capture_page_items(page_url, config)
        print(f"[capture] {index}/{len(video_pages)} found {len(items)} media urls")
        found.extend(items)
        if config.delay_seconds > 0 and index < len(video_pages):
            sleep(config.delay_seconds)

    return _filter_items(_dedupe(found), config, now)


def discover_video_pages(config: CrawlConfig) -> list[str]:
    pages: list[str] = []
    capture_config = network_capture_config(config)
    for seed in config.seeds:
        print(f"[scan] seed: {seed}")
        if is_video_page_url(seed):
            pages.append(seed)
            continue
        video_ids = capture_video_ids(seed, capture_config, config.max_pages)
        pages.extend(video_page_url(seed, video_id) for video_id in video_ids)
    return _dedupe_strings(pages)


def capture_page_items(page_url: str, config: CrawlConfig) -> list[MediaItem]:
    try:
        return capture_media_items(
            page_url,
            network_capture_config(config),
        )
    except (OSError, TimeoutError) as exc:
        print(f"[warn] network capture failed: {page_url} ({exc})")
        return []


def network_capture_config(config: CrawlConfig) -> NetworkCaptureConfig:
    return NetworkCaptureConfig(
        timeout_seconds=config.network_capture_seconds,
        user_agent=config.user_agent,
        browser_path=config.browser_path,
    )


def _filter_items(
    items: list[MediaItem],
    config: CrawlConfig,
    now: datetime | None,
) -> list[MediaItem]:
    filtered = []
    for item in items:
        if item.published_at is None and config.include_undated:
            filtered.append(item)
            continue
        if is_within_days(item.published_at, config.days, now):
            filtered.append(item)
    return filtered


def _dedupe(items: list[MediaItem]) -> list[MediaItem]:
    seen = set()
    unique = []
    for item in items:
        if item.url in seen:
            continue
        seen.add(item.url)
        unique.append(item)
    return unique


def _dedupe_strings(values: list[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique
