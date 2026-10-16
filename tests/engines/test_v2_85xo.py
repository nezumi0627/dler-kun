import asyncio
from datetime import datetime, timezone

import pytest

from dler_kun2.domain.contracts import CrawlRequest
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.engines.xo85.adapter import Xo85Engine
from dler_kun2.engines.xo85.dates import parse_date, within_days
from dler_kun2.engines.xo85.listing_parser import parse_listing
from dler_kun2.engines.xo85.seeds import resolve_seeds
from dler_kun2.engines.xo85.video_parser import parse_media_page

NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


def test_nested_current_and_legacy_cards_parse_relative_dates():
    html = '''<a class="drop-card" href="/ja/v/7.html"><div class="card-title">featured</div><span class="tools-text">1日前</span></a>
    <div class="item"><a href="/ja/v/7.html"><strong class="title">actual title</strong><div class="added"><em>30日前</em></div><img data-webp="/thumb.webp"></a></div>
    <div class="thumb thumb_rel item"><a href="/ja/video/8/example/"><span class="thumb-item-date">2 days ago</span></a></div>'''
    items = parse_listing(html, "https://www.85po.net/ja/latest-updates/", NOW)
    assert [item.video_id for item in items] == ["7", "8"]
    assert items[0].title == "actual title"
    assert items[0].published_at == datetime(2026, 9, 16, tzinfo=timezone.utc)
    assert items[0].thumbnail_url == "https://www.85po.net/thumb.webp"


def test_date_parsing_localized_and_window():
    for text in ("6日前", "6天前", "6 days ago"):
        assert parse_date(text, NOW) == datetime(2026, 10, 10, tzinfo=timezone.utc)
    assert within_days(parse_date("20日前", NOW), 20, NOW)
    assert not within_days(parse_date("21日前", NOW), 20, NOW)


def test_seed_alias_expands_without_accepting_unverified_hosts():
    assert resolve_seeds(("latest-updates",), {}) == ("https://www.85po.net/ja/latest-updates/",)
    assert resolve_seeds((), {})[0].startswith("https://www.85po.net/")


@pytest.mark.parametrize("seed", ["latest-updatez", "http://85po.net/latest-updates", "https://85po.net.evil.test/latest-updates", "https://user@85po.net/latest-updates"])
def test_explicit_invalid_seed_is_rejected_instead_of_crawling_defaults(seed):
    with pytest.raises(EngineError) as error:
        resolve_seeds((seed,), {})
    assert error.value.code is ErrorCode.INVALID_REQUEST


def test_invalid_sources_option_is_rejected_instead_of_crawling_defaults():
    with pytest.raises(EngineError) as error:
        resolve_seeds((), {"sources": ["latest-updatez"]})
    assert error.value.code is ErrorCode.INVALID_REQUEST


def test_media_parser_selects_best_bitrate_and_redacts_plan():
    url, uploaded = parse_media_page('''<a href="https://cdn.test/get_file/a.mp4?br=400">low</a>
      <a href="https://cdn.test/get_file/b.mp4?br=1200&download=true">high</a>
      <meta itemprop="uploadDate" content="2026-10-01T10:00:00Z">''', "https://www.85po.net/ja/v/1.html")
    assert url and "b.mp4" in url
    assert uploaded is not None and uploaded.year == 2026


def test_old_pages_do_not_get_truncated_by_featured_cards():
    page = '''<a class="drop-card" href="/ja/v/900.html"><div class="card-title">featured</div><span class="tools-text">1日前</span></a>
    <div class="item"><a href="/ja/v/100.html"><strong class="title">old</strong><div class="added">30日前</div></a></div>'''
    fetched = []

    class Response:
        async def text(self):
            return page

    class Client:
        async def request(self, method, url, **kwargs):
            fetched.append(url)
            return Response()

    result = asyncio.run(Xo85Engine(Client()).crawl(CrawlRequest("85xo", ("https://www.85po.net/ja/latest-updates/",), 20, {"max_pages": 8})))
    assert result.plans == ()
    assert len(fetched) == 2


def test_undated_cards_break_old_page_streak_so_later_recent_page_is_kept():
    pages = {
        1: '<div class="item"><a href="/ja/v/1.html"><span class="title">old</span><span class="added">30日前</span></a></div>',
        2: '<div class="item"><a href="/ja/v/2.html"><span class="title">old</span><span class="added">31日前</span></a></div><div class="item"><a href="/ja/v/3.html"><span class="title">unknown date</span></a></div>',
        3: '<div class="item"><a href="/ja/v/4.html"><span class="title">recent</span><span class="added">1日前</span></a></div>',
    }
    fetched = []

    class Response:
        def __init__(self, html):
            self.html = html

        async def text(self):
            return self.html

    class Client:
        async def request(self, method, url, **kwargs):
            fetched.append(url)
            if "/v/4.html" in url:
                return Response('<a href="https://cdn.test/get_file/recent.mp4?br=800">video</a>')
            page_number = 1 if "/2/" not in url and "/3/" not in url else 2 if "/2/" in url else 3
            return Response(pages[page_number])

    result = asyncio.run(Xo85Engine(Client()).crawl(CrawlRequest(
        "85xo", ("https://www.85po.net/ja/latest-updates/",), 20, {"max_pages": 6}
    )))
    assert len(result.plans) == 1
    assert result.plans[0].metadata["video_id"] == "4"
    assert any("/3/" in url for url in fetched)


def test_include_undated_option_includes_items_without_listing_dates():
    listing = '<div class="item"><a href="/ja/v/5.html"><span class="title">no date</span></a></div>'
    fetched = []

    class Response:
        def __init__(self, html):
            self.html = html

        async def text(self):
            return self.html

    class Client:
        async def request(self, method, url, **kwargs):
            fetched.append(url)
            if "/v/5.html" in url:
                return Response('<a href="https://cdn.test/get_file/undated.mp4?br=800">video</a>')
            return Response(listing)

    result = asyncio.run(Xo85Engine(Client()).crawl(CrawlRequest(
        "85xo", ("https://www.85po.net/ja/latest-updates/",), 20,
        {"max_pages": 1, "include_undated": True},
    )))
    assert result.discovered == 1
    assert result.plans[0].metadata["video_id"] == "5"
