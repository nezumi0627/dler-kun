import asyncio

from dler_kun2.domain.contracts import CrawlRequest, DownloadRequest
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.engines.mvfile.adapter import MvfileEngine
from dler_kun2.engines.mvfile.parser import Entry, parse_info, parse_list


def test_different_info_and_list_envelopes():
    info = {"code": 0, "data": {"info": {"netDiskInfo": {"shortLink": "ABCD", "name": "clip", "originUrl": "https://cdn.test/clip.mp4"}, "extraInfo": {"externalLinks": "CHNL"}}}}
    assert parse_info(info, "ABCD").channel == "CHNL"
    rows, total = parse_list({"code": 0, "data": {"list": [{"netDiskInfo": {"shortLink": "EFGH", "originUrl": "https://cdn.test/null"}}], "total": 1}})
    assert total == 1
    assert rows[0].media_url is None


def test_partial_related_collection_and_direct_media():
    class Client:
        async def info(self, domain, code):
            if code == "ROOT":
                return Entry("ROOT", "root", True, None)
            if code == "LOST":
                return Entry("LOST", "gone", False, None)
            return Entry(code, "same", False, f"https://cdn.test/{code}.mp4")

        async def list(self, domain, code, page, page_size=50):
            if page == 1:
                return ((Entry("AAAA", "same", False, "https://cdn.test/AAAA.mp4"), Entry("BBBB", "same", False, "https://cdn.test/BBBB.mp4"), Entry("LOST", "missing", False, None)), 60)
            raise EngineError(ErrorCode.NETWORK_ERROR, "pagination interrupted")

    engine = MvfileEngine(Client())
    result = asyncio.run(engine.crawl(CrawlRequest("mvfile", ("https://gofile.bar/d/ROOT",), None)))
    assert result.discovered == 3
    assert result.unavailable == 1
    assert len(result.plans) == 2
    assert len(result.errors) == 1
    assert {p.metadata["share_code"] for p in result.plans} == {"AAAA", "BBBB"}
    assert all(p.media_kind == "direct" for p in result.plans)
    plan = asyncio.run(engine.resolve_download(DownloadRequest("https://gofile.bar/d/AAAA")))
    assert plan.media_kind == "direct"


def test_related_channel_keeps_root_item_and_stops_pagination():
    class Client:
        async def info(self, domain, code):
            if code == "ROOT":
                return Entry("ROOT", "original", False, "https://cdn.example/root.mp4", channel="CHNL")
            return Entry("CHNL", "channel", False, None)

        async def list(self, domain, code, page, page_size=50):
            assert code == "CHNL"
            assert page == 1
            return ((Entry("NEXT", "another", False, "https://cdn.example/next.mp4"),), None)

    result = asyncio.run(MvfileEngine(Client()).crawl(CrawlRequest("mvfile", ("https://gofile.bar/d/ROOT",), None)))
    assert {p.metadata["share_code"] for p in result.plans} == {"ROOT", "NEXT"}
    assert result.errors == ()


def test_media_url_uses_second_valid_fallback():
    rows, _ = parse_list({"data": {"list": [{"netDiskInfo": {
        "shortLink": "GOOD", "originUrl": "https://cdn.example/null", "fileUrl": "https://cdn.example/video.mp4"
    }}]}})
    assert rows[0].media_url == "https://cdn.example/video.mp4"
