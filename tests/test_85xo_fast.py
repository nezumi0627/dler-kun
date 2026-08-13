import threading
from datetime import datetime, timezone

from dler_kun.engines.engine_85xo import (
    discover_listing_items,
    parse_listing_items,
    select_best_media_url,
)


def test_parse_listing_item_with_relative_date() -> None:
    html = """
    <div class="thumb thumb_rel item ">
      <a href="https://www.85xo.com/v/32568/title/" title="Sample">
        <div class="thumb-item thumb-item-date"><i></i> 3天前 </div>
      </a>
    </div>
    """
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    items = parse_listing_items(html, "https://www.85xo.com/latest-updates/", now)
    assert len(items) == 1
    assert items[0].title == "Sample"
    assert items[0].published_at is not None
    assert items[0].published_at.day == 12


def test_parse_listing_item_with_month_date() -> None:
    html = """
    <div class="thumb thumb_rel item ">
      <a href="https://www.85xo.com/v/1/a/" title="Old">
        <div class="thumb-item thumb-item-date"><i></i> 2ヶ月前 </div>
      </a>
    </div>
    """
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    items = parse_listing_items(html, "https://www.85xo.com/latest-updates/", now)
    assert items[0].published_at is not None
    assert (now - items[0].published_at).days == 60


def test_selects_download_true_highest_bitrate() -> None:
    html = """
    https://www.85xo.com/get_file/3/a/32000/1/1.mp4/?br=299
    https://www.85xo.com/get_file/3/b/32000/1/1_720p.mp4/?download=true&br=439
    https://www.85xo.com/get_file/3/c/32000/1/1_1080p.mp4/?download=true&br=819
    """
    selected = select_best_media_url(html)
    assert selected is not None
    assert "1080p" in selected
    assert "br=819" in selected


def test_select_ignores_screenshots() -> None:
    html = "https://www.85xo.com/get_file/0/d/32000/1/screenshots/1.jpg/"
    assert select_best_media_url(html) is None


def test_discover_listing_items_dedupes_and_filters() -> None:
    listing = """
    <div class="thumb thumb_rel item ">
      <a href="https://www.85xo.com/v/10/a/" title="A">
        <div class="thumb-item thumb-item-date"><i></i> 1天前 </div>
      </a>
    </div>
    <div class="thumb thumb_rel item ">
      <a href="https://www.85xo.com/v/11/b/" title="B">
        <div class="thumb-item thumb-item-date"><i></i> 2年前 </div>
      </a>
    </div>
    """
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    items = discover_listing_items(
        ["https://www.85xo.com/latest-updates/"],
        days=10,
        max_pages=1,
        timeout_seconds=1.0,
        now=now,
        fetcher=lambda url, timeout: listing,
    )
    assert [item.title for item in items] == ["A"]


def test_discover_respects_stop_event() -> None:
    stop = threading.Event()
    stop.set()
    items = discover_listing_items(
        ["https://www.85xo.com/latest-updates/"],
        days=10,
        max_pages=3,
        timeout_seconds=1.0,
        now=datetime(2026, 7, 15, tzinfo=timezone.utc),
        fetcher=lambda url, timeout: "",
        stop_event=stop,
    )
    assert items == []
