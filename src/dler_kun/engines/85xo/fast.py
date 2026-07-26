from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from ...managers import DownloadCacheManager
from ...models import CacheStatus


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
DATE_RE = re.compile(
    r'class="[^"]*thumb-item-date[^"]*".*?(?:</i>)?\s*(?P<date>[^<]+)</div>',
    re.S | re.I,
)
DATE_ALT_RES = (
    re.compile(r"thumb-item-date.*?</i>\s*(?P<date>[^<]+)</div>", re.S | re.I),
    re.compile(r'class="date"[^>]*>\s*(?P<date>[^<]+)\s*<', re.I),
)
VIDEO_PAGE_ID_RE = re.compile(r"/v/(?P<id>\d+)/")
DURATION_RE = re.compile(
    r'<div class="time"><span[^>]*></span>\s*(?P<duration>[^<]+)</div>', re.S
)
GET_FILE_RE = re.compile(r'https?://[^"\'<>\s]+/get_file/[^"\'<>\s]+?\.mp4[^"\'<>\s]*')
LD_JSON_RE = re.compile(
    r'<script type="application/ld\+json">\s*(?P<json>{.*?})\s*</script>', re.S
)
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
    resolve_workers: int = 6,
    include_undated: bool = False,
    now: datetime | None = None,
    fetcher: Callable[[str, float], str] | None = None,
) -> list[FastMediaItem]:
    fetcher = fetcher or fetch_html
    now = now or datetime.now(timezone.utc)
    candidates = discover_listing_items(
        seeds, days, max_pages, timeout_seconds, now, fetcher, include_undated
    )
    return resolve_media_items(candidates, timeout_seconds, fetcher, resolve_workers)


def resolve_media_items(
    candidates: list[FastListingItem],
    timeout_seconds: float,
    fetcher: Callable[[str, float], str],
    resolve_workers: int,
) -> list[FastMediaItem]:
    resolved: dict[int, FastMediaItem] = {}
    max_workers = max(1, resolve_workers)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                resolve_media_item,
                index,
                len(candidates),
                candidate,
                timeout_seconds,
                fetcher,
            ): index
            for index, candidate in enumerate(candidates, start=1)
        }
        for future in as_completed(futures):
            index = futures[future]
            item = future.result()
            if item is not None:
                resolved[index] = item
    return [resolved[index] for index in sorted(resolved)]


def resolve_media_item(
    index: int,
    total: int,
    candidate: FastListingItem,
    timeout_seconds: float,
    fetcher: Callable[[str, float], str],
) -> FastMediaItem | None:
    print(f"[fast-capture] {index}/{total} {candidate.page_url}")
    try:
        video_html = fetcher(candidate.page_url, timeout_seconds)
    except OSError as exc:
        print(f"[warn] video page fetch failed: {candidate.page_url} ({exc})")
        return None
    media_url = select_best_media_url(video_html)
    if not media_url:
        print(f"[warn] media url not found: {candidate.page_url}")
        return None
    published_at = parse_video_published_at(video_html) or candidate.published_at
    return FastMediaItem(
        url=media_url,
        source_page=candidate.page_url,
        title=candidate.title,
        published_at=published_at,
    )


def discover_listing_items(
    seeds: list[str],
    days: int,
    max_pages: int,
    timeout_seconds: float,
    now: datetime,
    fetcher: Callable[[str, float], str],
    include_undated: bool = False,
) -> list[FastListingItem]:
    results: list[FastListingItem] = []
    seen_video_ids: set[str] = set()
    for seed in seeds:
        old_pages = 0
        for page_number in range(1, max(1, max_pages) + 1):
            page_url = listing_page_url(seed, page_number)
            print(f"[fast-scan] listing page {page_number}/{max_pages}: {page_url}")
            html = fetcher(page_url, timeout_seconds)
            items = parse_listing_items(html, page_url, now)
            within = [
                item
                for item in items
                if is_within_days(item.published_at, days, now)
                or (include_undated and item.published_at is None)
            ]
            for item in within:
                video_id = video_page_key(item.page_url)
                if video_id not in seen_video_ids:
                    seen_video_ids.add(video_id)
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


def parse_listing_items(
    html: str, base_url: str, now: datetime
) -> list[FastListingItem]:
    items: list[FastListingItem] = []
    for card in CARD_RE.findall(html):
        href = match_group(HREF_RE, card, "href")
        if not href:
            continue
        title = unescape(match_group(TITLE_RE, card, "title") or "")
        date_text = extract_listing_date_text(card)
        items.append(
            FastListingItem(
                page_url=urljoin(base_url, href),
                title=" ".join(title.split()),
                published_at=parse_published_at(date_text, now),
                thumbnail_url=match_group(THUMB_RE, card, "thumb"),
                duration=" ".join(
                    (match_group(DURATION_RE, card, "duration") or "").split()
                )
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


def extract_listing_date_text(card: str) -> str:
    for pattern in (DATE_RE, *DATE_ALT_RES):
        match = pattern.search(card)
        if match:
            return unescape((match.group("date") or "").strip())
    return ""


def video_page_key(page_url: str) -> str:
    match = VIDEO_PAGE_ID_RE.search(page_url)
    return match.group("id") if match else page_url


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
        day_match = re.search(
            r"(?P<days>\d+)\s*(?:天前|日前|days?\s+ago)", normalized, re.I
        )
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
    import sys

    for candidate in (project_path, project_path / "lib"):
        if (candidate / "xo_dler").exists():
            path = str(candidate)
            if path not in sys.path:
                sys.path.insert(0, path)
            break
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


def download_existing_items_parallel(
    items: list,
    config,
    max_workers: int = 4,
    read_timeout_seconds: float = 30.0,
    attempts: int = 2,
    max_time_seconds: float | None = None,
    cache_manager: DownloadCacheManager | None = None,
    progress_callback: Callable[[dict], None] | None = None,
) -> list[Path]:
    from xo_dler.downloader import target_path, unique_target_path, write_metadata

    config.output_dir.mkdir(parents=True, exist_ok=True)
    max_workers = max(1, max_workers)
    curl_path = shutil.which("curl")
    cache = cache_manager
    downloaded: list[Path] = []
    tasks = []
    start_time = time.monotonic()
    progress_lock = threading.Lock()
    completed = 0
    total = len(items)

    def emit_progress(current_file: str = "") -> None:
        if not progress_callback:
            return
        elapsed = max(0.001, time.monotonic() - start_time)
        with progress_lock:
            done = completed
        rate = done / elapsed
        remaining = max(0, total - done)
        eta_seconds = int(remaining / rate) if rate > 0 else 0
        progress_callback(
            {
                "phase": "download",
                "current_file": current_file,
                "completed_files": done,
                "total_files": total,
                "progress": round((done / total) * 100, 2) if total else 100,
                "speed": f"{rate:.2f} files/s",
                "eta": f"{eta_seconds}s",
            }
        )

    def mark_completed(current_file: str = "") -> None:
        nonlocal completed
        with progress_lock:
            completed += 1
        emit_progress(current_file)

    for item in items:
        target = target_path(config.output_dir, item)
        cache_key = cache_key_for_url(item.url)
        metadata_path = target.with_suffix(target.suffix + ".json")
        is_cached_complete = bool(cache and cache.is_complete(cache_key))
        is_sidecar_complete = (
            target.exists() and metadata_path.exists() and target.stat().st_size > 0
        )
        if config.skip_existing and (is_cached_complete or is_sidecar_complete):
            print(f"[skip] exists: {target}")
            if cache:
                cache.mark(cache_key, item.url, target, CacheStatus.COMPLETE, "85xo")
            downloaded.append(target)
            mark_completed(str(target))
            continue
        part_path = target.with_suffix(target.suffix + ".part")
        if target.exists():
            target.unlink(missing_ok=True)
            if cache:
                cache.mark(cache_key, item.url, target, CacheStatus.CORRUPT, "85xo")
        elif part_path.exists() and not should_keep_partial_after_failure(
            part_path, bool(curl_path)
        ):
            part_path.unlink(missing_ok=True)
            if cache:
                cache.mark(cache_key, item.url, part_path, CacheStatus.CORRUPT, "85xo")
        if target.exists():
            target = unique_target_path(target)
        tasks.append((item, target, cache_key))
    emit_progress()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                download_item_robust,
                item,
                target,
                config,
                read_timeout_seconds,
                attempts,
                curl_path,
                cache,
                cache_key,
                max_time_seconds,
            ): (item, target, cache_key)
            for item, target, cache_key in tasks
        }
        for future in as_completed(futures):
            item, target, cache_key = futures[future]
            try:
                if future.result():
                    write_metadata(target, item)
                    if cache:
                        cache.mark(
                            cache_key, item.url, target, CacheStatus.COMPLETE, "85xo"
                        )
                    downloaded.append(target)
                elif cache:
                    cache.mark(cache_key, item.url, target, CacheStatus.FAILED, "85xo")
            except Exception as exc:  # noqa: BLE001 - keep long crawl moving.
                print(
                    f"[warn] download worker failed: {getattr(item, 'url', '')} ({exc})"
                )
                if cache:
                    cache.mark(
                        cache_key,
                        item.url,
                        target,
                        CacheStatus.FAILED,
                        "85xo",
                        str(exc),
                    )
            finally:
                mark_completed(str(target))

    return downloaded


def download_item_robust(
    item,
    target: Path,
    config,
    read_timeout_seconds: float,
    attempts: int,
    curl_path: str | None,
    cache: DownloadCacheManager | None,
    cache_key: str,
    max_time_seconds: float | None = None,
) -> bool:
    import requests
    from xo_dler.downloader import download_headers

    part_path = target.with_suffix(target.suffix + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)
    use_curl = bool(curl_path)

    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            headers = download_headers(item, config)
            if cache:
                cache.mark(cache_key, item.url, part_path, CacheStatus.PARTIAL, "85xo")
            if use_curl:
                download_with_curl(
                    curl_path,
                    item.url,
                    part_path,
                    headers,
                    read_timeout_seconds,
                    max_time_seconds=max_time_seconds,
                )
            else:
                with requests.get(
                    item.url,
                    headers=headers,
                    stream=True,
                    timeout=(10, read_timeout_seconds),
                ) as response:
                    response.raise_for_status()
                    with part_path.open("wb") as file:
                        for chunk in response.iter_content(
                            chunk_size=config.chunk_size
                        ):
                            if chunk:
                                file.write(chunk)
            if not part_path.exists() or part_path.stat().st_size <= 0:
                raise OSError("empty download")
            part_path.replace(target)
            print(f"[done] {target}")
            return True
        except (OSError, requests.RequestException, subprocess.SubprocessError) as exc:
            last_error = exc
            print(
                f"[warn] download attempt {attempt}/{attempts} failed: {item.url} ({exc})"
            )
            if should_keep_partial_after_failure(part_path, use_curl):
                if cache:
                    cache.mark(
                        cache_key,
                        item.url,
                        part_path,
                        CacheStatus.PARTIAL,
                        "85xo",
                        str(exc),
                    )
            else:
                part_path.unlink(missing_ok=True)

    print(f"[warn] download failed: {item.url} ({last_error})")
    return False


def should_keep_partial_after_failure(part_path: Path, use_curl: bool) -> bool:
    return use_curl and part_path.exists() and part_path.stat().st_size > 0


def cache_key_for_url(url: str) -> str:
    import hashlib

    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def direct_media_items_from_url(
    url: str,
    timeout_seconds: float = 30.0,
    fetcher: Callable[[str, float], str] | None = None,
) -> list[FastMediaItem]:
    fetcher = fetcher or fetch_html
    lowered = url.lower()
    if "/get_file/" in lowered and ".mp4" in lowered:
        return [FastMediaItem(url=url, source_page=url)]
    video_html = fetcher(url, timeout_seconds)
    media_url = select_best_media_url(video_html)
    if not media_url:
        return []
    title = match_group(TITLE_RE, video_html, "title")
    published_at = parse_video_published_at(video_html)
    return [
        FastMediaItem(
            url=media_url,
            source_page=url,
            title=unescape(title) if title else None,
            published_at=published_at,
        )
    ]


def build_curl_download_command(
    curl_path: str,
    url: str,
    output_path: Path,
    headers: dict[str, str],
    read_timeout_seconds: float,
    max_time_seconds: float | None = None,
) -> list[str]:
    # Stall detection only by default; optional --max-time for hard caps.
    speed_time = max(10, int(read_timeout_seconds))
    command = [
        curl_path,
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--connect-timeout",
        "10",
        "--speed-limit",
        "1024",
        "--speed-time",
        str(speed_time),
        "--output",
        str(output_path),
    ]
    # Resume only when a non-empty partial already exists. An empty `.part`
    # plus `--continue-at -` can hang on some CDNs (Range: bytes=0-).
    if output_path.exists() and output_path.stat().st_size > 0:
        command[5:5] = ["--continue-at", "-"]
    if max_time_seconds is not None and max_time_seconds > 0:
        command.extend(["--max-time", str(int(max_time_seconds))])
    for key, value in headers.items():
        command.extend(["--header", f"{key}: {value}"])
    command.append(url)
    return command


def download_with_curl(
    curl_path: str,
    url: str,
    output_path: Path,
    headers: dict[str, str],
    read_timeout_seconds: float,
    max_time_seconds: float | None = None,
) -> None:
    command = build_curl_download_command(
        curl_path,
        url,
        output_path,
        headers,
        read_timeout_seconds,
        max_time_seconds=max_time_seconds,
    )
    proc_timeout = None
    if max_time_seconds is not None and max_time_seconds > 0:
        proc_timeout = int(max_time_seconds) + 10
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=proc_timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise OSError(completed.stderr.strip() or f"curl exit {completed.returncode}")


def match_group(pattern: re.Pattern[str], text: str, group: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return match.group(group).strip()
