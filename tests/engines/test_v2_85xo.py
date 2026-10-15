import asyncio
from datetime import datetime, timezone

from dler_kun2.domain.contracts import CrawlRequest
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
