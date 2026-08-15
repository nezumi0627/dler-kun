from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from ...managers import DownloadCacheManager
from ...models import CacheStatus

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class DownloadCancelled(Exception):
    """Raised when a stop (Ctrl+C) interrupts an in-flight transfer."""

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
    discover_workers: int = 6,
    now: datetime | None = None,
    fetcher: Callable[[str, float], str] | None = None,
    stop_event: threading.Event | None = None,
    resolve_cache: Any = None,
) -> list[FastMediaItem]:
    fetcher = fetcher or fetch_html
    now = now or datetime.now(timezone.utc)
    candidates = discover_listing_items(
        seeds,
        days,
        max_pages,
        timeout_seconds,
        now,
        fetcher,
        include_undated,
        workers=discover_workers,
        stop_event=stop_event,
    )
    return resolve_media_items(
        candidates,
        timeout_seconds,
        fetcher,
        resolve_workers,
        stop_event,
        resolve_cache,
    )


def resolve_media_items(
    candidates: list[FastListingItem],
    timeout_seconds: float,
    fetcher: Callable[[str, float], str],
    resolve_workers: int,
    stop_event: threading.Event | None = None,
    resolve_cache: Any = None,
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
                stop_event,
                resolve_cache,
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
    stop_event: threading.Event | None = None,
    resolve_cache: Any = None,
) -> FastMediaItem | None:
    if stop_event is not None and stop_event.is_set():
        return None
    print(f"[fast-capture] {index}/{total} {candidate.page_url}")
    cache_key = video_page_key(candidate.page_url)
    if resolve_cache is not None:
        cached = resolve_cache.get(cache_key)
        if cached:
            return FastMediaItem(
                url=cached,
                source_page=candidate.page_url,
                title=candidate.title,
                published_at=candidate.published_at,
            )
    try:
        video_html = fetcher(candidate.page_url, timeout_seconds)
    except OSError as exc:
        print(f"[warn] video page fetch failed: {candidate.page_url} ({exc})")
        return None
    media_url = select_best_media_url(video_html)
    if not media_url:
        print(f"[warn] media url not found: {candidate.page_url}")
        return None
    if resolve_cache is not None:
        resolve_cache.set(cache_key, media_url)
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
    workers: int = 6,
    stop_event: threading.Event | None = None,
) -> list[FastListingItem]:
    results: list[FastListingItem] = []
    seen_video_ids: set[str] = set()
    max_workers = max(1, workers)
    for seed in seeds:
        if stop_event is not None and stop_event.is_set():
            break
        old_pages = 0
        page_numbers = list(range(1, max(1, max_pages) + 1))
        for start in range(0, len(page_numbers), max_workers):
            if stop_event is not None and stop_event.is_set():
                break
            batch = page_numbers[start : start + max_workers]
            scanned = _scan_pages_batch(
                seed,
                batch,
                days,
                timeout_seconds,
                now,
                fetcher,
                include_undated,
                stop_event,
            )
            broke = False
            for page_number in sorted(scanned):
                items, within = scanned[page_number]
                for item in within:
                    video_id = video_page_key(item.page_url)
                    if video_id not in seen_video_ids:
                        seen_video_ids.add(video_id)
                        results.append(item)
                dated_items = [item for item in items if item.published_at is not None]
                if items and dated_items and not within:
                    old_pages += 1
                    if old_pages >= 2:
                        broke = True
                        break
                else:
                    old_pages = 0
            if broke:
                break
    return results


def _scan_pages_batch(
    seed: str,
    page_numbers: list[int],
    days: int,
    timeout_seconds: float,
    now: datetime,
    fetcher: Callable[[str, float], str],
    include_undated: bool,
    stop_event: threading.Event | None = None,
) -> dict[int, tuple[list[FastListingItem], list[FastListingItem]]]:
    scanned: dict[int, tuple[list[FastListingItem], list[FastListingItem]]] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(page_numbers))) as executor:
        futures = {
            executor.submit(
                _scan_listing_page,
                seed,
                page_number,
                days,
                timeout_seconds,
                now,
                fetcher,
                include_undated,
                stop_event,
            ): page_number
            for page_number in page_numbers
        }
        for future in as_completed(futures):
            scanned[futures[future]] = future.result()
    return scanned


def _scan_listing_page(
    seed: str,
    page_number: int,
    days: int,
    timeout_seconds: float,
    now: datetime,
    fetcher: Callable[[str, float], str],
    include_undated: bool,
    stop_event: threading.Event | None = None,
) -> tuple[list[FastListingItem], list[FastListingItem]]:
    if stop_event is not None and stop_event.is_set():
        return [], []
    page_url = listing_page_url(seed, page_number)
    print(f"[fast-scan] listing page {page_number}: {page_url}")
    html = fetcher(page_url, timeout_seconds)
    items = parse_listing_items(html, page_url, now)
    within = [
        item
        for item in items
        if is_within_days(item.published_at, days, now)
        or (include_undated and item.published_at is None)
    ]
    print(f"[fast-scan] page {page_number}: +{len(within)} within {days} days")
    return items, within


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
    from .xo_dler.dates import parse_published_at

    return parse_published_at(text, now)


def is_within_days(value: datetime | None, days: int, now: datetime) -> bool:
    from .xo_dler.dates import is_within_days

    return is_within_days(value, days, now)


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def to_existing_media_items(items: Iterable[FastMediaItem]):
    from .xo_dler.models import MediaItem

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
    write_metadata_sidecar: bool = False,
    stop_event: threading.Event | None = None,
    local_addr: str = "",
    proxy: str = "",
) -> list[Path]:
    from .xo_dler.downloader import target_path, unique_target_path, write_metadata

    if stop_event is not None and stop_event.is_set():
        return []
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
    byte_progress: dict[Path, tuple[int, float | None]] = {}

    def emit_progress(current_file: str = "") -> None:
        if not progress_callback:
            return
        elapsed = max(0.001, time.monotonic() - start_time)
        with progress_lock:
            done = completed
            snapshot = list(byte_progress.values())
        rate = done / elapsed
        remaining = max(0, total - done)
        eta_seconds = int(remaining / rate) if rate > 0 else 0
        payload = {
            "phase": "download",
            "current_file": current_file,
            "completed_files": done,
            "total_files": total,
            "progress": round((done / total) * 100, 2) if total else 100,
            "speed": f"{rate:.2f} files/s",
            "eta": f"{eta_seconds}s",
        }
        # Prefer byte-level progress (from in-flight downloads) so a single
        # large file doesn't look stuck at 0% until it fully completes.
        bytes_done = sum(done_bytes for done_bytes, _ in snapshot)
        resolved_totals = [t for _, t in snapshot if t is not None]
        if snapshot and len(resolved_totals) == len(snapshot) and sum(resolved_totals) > 0:
            payload["bytes_done"] = bytes_done
            payload["bytes_total"] = sum(resolved_totals)
        progress_callback(payload)

    def mark_completed(current_file: str = "") -> None:
        nonlocal completed
        with progress_lock:
            completed += 1
            if current_file:
                byte_progress.pop(Path(current_file), None)
        emit_progress(current_file)

    def update_byte_progress(
        target: Path, done_bytes: int, total_bytes: float | None
    ) -> None:
        with progress_lock:
            byte_progress[target] = (done_bytes, total_bytes)
        emit_progress(str(target))

    for item in items:
        target = target_path(config.output_dir, item)
        cache_key = cache_key_for_url(item.url)
        metadata_path = target.with_suffix(target.suffix + ".json")
        is_cached_complete = bool(cache and cache.is_complete(cache_key))
        is_sidecar_complete = write_metadata_sidecar and (
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
                (lambda done_bytes, total_bytes, target=target: update_byte_progress(
                    target, done_bytes, total_bytes
                ))
                if progress_callback
                else None,
                stop_event,
                local_addr,
                proxy,
            ): (item, target, cache_key)
            for item, target, cache_key in tasks
        }
        try:
            for future in as_completed(futures):
                item, target, cache_key = futures[future]
                try:
                    if future.result():
                        if write_metadata_sidecar:
                            write_metadata(target, item)
                        if cache:
                            cache.mark(
                                cache_key,
                                item.url,
                                target,
                                CacheStatus.COMPLETE,
                                "85xo",
                            )
                        downloaded.append(target)
                    elif cache:
                        cache.mark(
                            cache_key, item.url, target, CacheStatus.FAILED, "85xo"
                        )
                except Exception as exc:  # noqa: BLE001 - keep long crawl moving.
                    print(
                        f"[warn] download worker failed: "
                        f"{getattr(item, 'url', '')} ({exc})"
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
        except KeyboardInterrupt:
            if stop_event is not None:
                stop_event.set()
            raise

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
    on_progress: Callable[[int, float | None], None] | None = None,
    stop_event: threading.Event | None = None,
    local_addr: str = "",
    proxy: str = "",
) -> bool:
    import requests

    from .xo_dler.downloader import download_headers

    if stop_event is not None and stop_event.is_set():
        return False
    part_path = target.with_suffix(target.suffix + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)
    use_curl = bool(curl_path)
    headers = download_headers(item, config)
    total_bytes = probe_content_length(item.url, headers) if on_progress else None

    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        stop_poll = threading.Event()
        poll_thread: threading.Thread | None = None
        if on_progress:
            poll_thread = threading.Thread(
                target=poll_part_progress,
                args=(part_path, total_bytes, on_progress, stop_poll),
                daemon=True,
            )
            poll_thread.start()
        try:
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
                    stop_event=stop_event,
                    local_addr=local_addr,
                    proxy=proxy,
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
                            if stop_event is not None and stop_event.is_set():
                                raise DownloadCancelled("interrupted by user")
                            if chunk:
                                file.write(chunk)
            if not part_path.exists() or part_path.stat().st_size <= 0:
                raise OSError("empty download")
            part_path.replace(target)
            if on_progress:
                on_progress(int(total_bytes or part_path.stat().st_size), total_bytes)
            print(f"[done] {target}")
            return True
        except DownloadCancelled:
            print(f"[stop] {item.url}")
            if not should_keep_partial_after_failure(part_path, use_curl):
                part_path.unlink(missing_ok=True)
            return False
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
        finally:
            stop_poll.set()
            if poll_thread:
                poll_thread.join(timeout=1.0)

    print(f"[warn] download failed: {item.url} ({last_error})")
    return False


def probe_content_length(url: str, headers: dict[str, str]) -> float | None:
    import requests

    try:
        probe_headers = {k: v for k, v in headers.items() if k.lower() != "range"}
        response = requests.head(
            url, headers=probe_headers, timeout=8, allow_redirects=True
        )
        length = response.headers.get("Content-Length")
        return float(length) if length else None
    except (requests.RequestException, ValueError):
        return None


def poll_part_progress(
    part_path: Path,
    total_bytes: float | None,
    on_progress: Callable[[int, float | None], None],
    stop_event: threading.Event,
) -> None:
    while not stop_event.wait(0.5):
        try:
            done = part_path.stat().st_size
        except OSError:
            done = 0
        on_progress(done, total_bytes)


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


def download_with_curl(
    curl_path: str,
    url: str,
    output_path: Path,
    headers: dict[str, str],
    read_timeout_seconds: float,
    max_time_seconds: float | None = None,
    stop_event: threading.Event | None = None,
    local_addr: str = "",
    proxy: str = "",
) -> None:
    from ...net import CurlCancelled, curl_download

    try:
        curl_download(
            url,
            output_path,
            curl_path=curl_path,
            headers=headers,
            local_addr=local_addr,
            proxy=proxy,
            read_timeout_seconds=read_timeout_seconds,
            max_time_seconds=max_time_seconds,
            # Resume only when a non-empty partial already exists. An empty
            # `.part` plus `--continue-at -` can hang on some CDNs.
            resume=output_path.exists() and output_path.stat().st_size > 0,
            stop_event=stop_event,
        )
    except CurlCancelled as exc:
        raise DownloadCancelled("interrupted by user") from exc


def match_group(pattern: re.Pattern[str], text: str, group: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return match.group(group).strip()
