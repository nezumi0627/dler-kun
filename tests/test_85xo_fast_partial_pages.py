from __future__ import annotations

import importlib
from datetime import datetime, timezone

import pytest

fast = importlib.import_module("dler_kun.engines.85xo.fast")


def test_listing_page_failure_preserves_other_page_and_reports_partial_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fetcher(url: str, _timeout: float) -> str:
        if url.endswith("/2/"):
            raise OSError("temporary listing failure")
        return '<div class="item"><a href="https://www.85po.net/ja/video/123/example/" title="Example"></a></div>'

    errors: list[str] = []
    scanned = fast._scan_pages_batch(
        "https://www.85po.net/ja/latest-updates/",
        [1, 2],
        10,
        5,
        datetime(2026, 10, 15, tzinfo=timezone.utc),
        fetcher,
        True,
        errors=errors,
    )

    assert list(scanned) == [1]
    assert scanned[1][0][0].page_url == "https://www.85po.net/ja/video/123/example/"
    assert errors == ["network_error"]
    assert "listing page 2 failed" in capsys.readouterr().out


def test_current_drop_card_layout_is_parsed_with_relative_date() -> None:
    html = '''
    <a class="drop-card" href="https://www.85po.net/ja/v/36631.html">
      <div class="card-image"><img data-webp="https://cdn.example.test/thumb.webp">
        <div class="duration">12:34</div>
      </div>
      <div class="card-title">Example title</div>
      <div class="card-tools"><span class="icon-calendar"></span>
        <span class="tools-text">6日前</span>
      </div>
    </a>'''

    items = fast.parse_listing_items(
        html,
        "https://www.85po.net/ja/latest-updates/",
        datetime(2026, 10, 15, tzinfo=timezone.utc),
    )

    assert len(items) == 1
    assert items[0].page_url == "https://www.85po.net/ja/v/36631.html"
    assert items[0].title == "Example title"
    assert items[0].published_at == datetime(2026, 10, 9, tzinfo=timezone.utc)
    assert fast.video_page_key(items[0].page_url) == "36631"


def test_current_list_item_layout_is_parsed_with_relative_date() -> None:
    html = '''
    <div class="item">
      <a href="https://www.85po.net/ja/v/36575.html">
        <img class="thumb" data-webp="https://cdn.example.test/thumb.webp">
        <strong class="title">Example title</strong>
        <div class="duration">12:34</div>
        <div class="added"><em>2日前</em></div>
      </a>
    </div>'''

    items = fast.parse_listing_items(
        html,
        "https://www.85po.net/ja/latest-updates/2/",
        datetime(2026, 10, 15, tzinfo=timezone.utc),
    )

    assert len(items) == 1
    assert items[0].page_url == "https://www.85po.net/ja/v/36575.html"
    assert items[0].published_at == datetime(2026, 10, 13, tzinfo=timezone.utc)


def test_featured_cards_do_not_prevent_old_page_early_stop() -> None:
    html = '''
    <a class="drop-card" href="https://www.85po.net/ja/v/36631.html">
      <div class="card-title">Featured</div>
      <span class="icon-calendar"></span><span class="tools-text">1日前</span>
    </a>
    <div class="item"><a href="https://www.85po.net/ja/v/30001.html">
      <strong class="title">Old listing</strong>
      <div class="added"><em>30日前</em></div>
    </a></div>'''
    fetched: list[str] = []

    def fetcher(url: str, _timeout: float) -> str:
        fetched.append(url)
        return html

    items = fast.discover_listing_items(
        ["https://www.85po.net/ja/latest-updates/"],
        days=20,
        max_pages=10,
        timeout_seconds=5,
        now=datetime(2026, 10, 15, tzinfo=timezone.utc),
        fetcher=fetcher,
        workers=1,
    )

    assert items == []
    assert len(fetched) == 2


def test_video_page_resolution_keeps_successes_and_reports_failures(
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    candidates = [
        fast.FastListingItem("https://85po.net/ja/v/1.html", "ok", now),
        fast.FastListingItem("https://85po.net/ja/v/2.html", "bad", now),
    ]

    def fetcher(url: str, _timeout: float) -> str:
        if url.endswith("/2.html"):
            raise RuntimeError("unexpected parser/network failure")
        return '<video src="https://cdn.example/get_file/video.mp4?br=720"></video>'

    errors: list[str] = []
    result = fast.resolve_media_items(
        candidates, 5, fetcher, 2, errors=errors
    )

    assert [item.source_page for item in result] == [candidates[0].page_url]
    assert errors == ["network_error"]
    assert "video page resolution failed" in capsys.readouterr().out


def test_failed_listing_page_breaks_old_page_streak() -> None:
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    fetched: list[str] = []

    def fetcher(url: str, _timeout: float) -> str:
        fetched.append(url)
        if url.endswith("/2/"):
            raise OSError("temporary failure")
        age = "30日前" if not url.endswith("/3/") else "2日前"
        return f'''<div class="item"><a href="https://www.85po.net/ja/v/{url[-2]}001.html">
          <strong class="title">Video</strong><div class="added"><em>{age}</em></div>
        </a></div>'''

    items = fast.discover_listing_items(
        ["https://www.85po.net/ja/latest-updates/"],
        days=20,
        max_pages=4,
        timeout_seconds=5,
        now=now,
        fetcher=fetcher,
        workers=1,
    )

    assert any(item.published_at == datetime(2026, 10, 13, tzinfo=timezone.utc) for item in items)
    assert len(fetched) == 4
