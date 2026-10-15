import asyncio

from dler_kun2.domain.contracts import DownloadRequest
from dler_kun2.engines.mixixxx.adapter import MixixxxEngine
from dler_kun2.engines.mixixxx.embed_parser import extract_embed_url
from dler_kun2.engines.mixixxx.listing_parser import listing_page_url, parse_listing


def test_current_wordpress_listing_is_parsed_and_deduplicated():
    html = '''<article class="post"><h2 class="post-title"><a href="https://jav-mixi.cc/scvp-22466/">Current title</a></h2></article>
    <article><a href="https://jav-mixi.cc/scvp-22466/">duplicate title</a></article>
    <a href="https://evil.example/other">external</a><a href="https://jav-mixi.cc/category/news/">category</a>'''
    pages = parse_listing(html, "https://jav-mixi.cc/")
    assert len(pages) == 1
    assert pages[0].url == "https://jav-mixi.cc/scvp-22466/"
    assert pages[0].title == "Current title"
    assert listing_page_url("https://jav-mixi.cc/", 2) == "https://jav-mixi.cc/page/2/"


def test_current_luluvido_iframe_is_allowed_but_untrusted_embed_is_rejected():
    assert extract_embed_url('<iframe src="https://luluvido.com/e/video123"></iframe>') == "https://luluvido.com/e/video123"
    assert extract_embed_url('<iframe src="https://evil.example/e/video123"></iframe>') is None


def test_resolver_canonicalizes_legacy_domain_and_extracts_current_embed():
    class Response:
        async def text(self):
            return '<iframe src="https://luluvido.com/e/abc123"></iframe>'

    class Client:
        async def request(self, method, url, **kwargs):
            assert url == "https://jav-mixi.cc/scvp-22466/"
            return Response()

    plan = asyncio.run(MixixxxEngine(Client()).resolve_download(DownloadRequest("https://mixi-xxx.cc/scvp-22466/")))
    assert plan.media_kind == "browser_hls"
    assert plan.source_url == "https://jav-mixi.cc/scvp-22466/"
    assert "abc123" not in str(plan.to_dict())


def test_browser_plan_download_stages_atomically_and_allocates_unique_names(tmp_path, monkeypatch):
    import dler_kun2.engines.mixixxx.adapter as adapter

    class FakeBrowser:
        def __init__(self, **kwargs):
            pass

        def download(self, _embed, output, *, concurrency):
            output.write_bytes(b"muxed video")
            return output

    monkeypatch.setattr(adapter, "BrowserHlsDownloader", FakeBrowser)
    class UnusedClient:
        async def request(self, method, url, **kwargs):
            raise AssertionError("download_plan does not fetch the page")

    engine = MixixxxEngine(UnusedClient())
    from dler_kun2.domain.plans import DownloadPlan

    plan = DownloadPlan("https://luluvido.com/e/hidden", "https://jav-mixi.cc/", "https://jav-mixi.cc/scvp-22466/", "browser_hls", "clip.mp4", None)
    first = asyncio.run(engine.download_plan(plan, tmp_path))
    second = asyncio.run(engine.download_plan(plan, tmp_path))
    assert first != second
    assert first.read_bytes() == second.read_bytes() == b"muxed video"
    assert not list(tmp_path.glob("*.stage.mp4"))


def test_hls_segments_are_written_in_order_without_aggregating_the_playlist(tmp_path):
    import base64
    import json
    from typing import cast

    from dler_kun2.engines.mixixxx.browser import _Cdp, _load_many

    class Socket:
        def __init__(self):
            self.events = [
                {"id": 2, "result": {"resource": {"stream": "two", "httpStatusCode": 200}}},
                {"id": 1, "result": {"resource": {"stream": "one", "httpStatusCode": 200}}},
            ]

        def recv(self, timeout):
            return json.dumps(self.events.pop(0))

    class Cdp:
        socket = Socket()

        def __init__(self):
            self.command = 0

        def send(self, method, params):
            self.command += 1
            return self.command

        def call(self, method, params, timeout=15):
            if method == "IO.read":
                data = {"one": b"first", "two": b"second"}[params["handle"]]
                return {"data": base64.b64encode(data).decode(), "base64Encoded": True, "eof": True}
            return {}

    paths = _load_many(cast(_Cdp, Cdp()), ["same", "same"], "frame", {}, 2, 5, tmp_path)
    assert [path.name for path in paths] == ["segment-000000.ts", "segment-000001.ts"]
    assert [path.read_bytes() for path in paths] == [b"first", b"second"]


def test_cancel_waits_for_browser_worker_before_cleaning_staging(tmp_path, monkeypatch):
    import threading

    import dler_kun2.engines.mixixxx.adapter as adapter
    from dler_kun2.domain.plans import DownloadPlan

    started = threading.Event()
    release = threading.Event()

    class SlowBrowser:
        def __init__(self, **kwargs):
            pass

        def download(self, _embed, output, *, concurrency):
            started.set()
            release.wait(2)
            output.write_bytes(b"complete")

    monkeypatch.setattr(adapter, "BrowserHlsDownloader", SlowBrowser)

    class UnusedClient:
        async def request(self, method, url, **kwargs):
            raise AssertionError

    async def scenario():
        engine = MixixxxEngine(UnusedClient())
        plan = DownloadPlan("https://luluvido.com/e/id", "https://jav-mixi.cc/", "https://jav-mixi.cc/post/", "browser_hls", "clip.mp4", None)
        task = asyncio.create_task(engine.download_plan(plan, tmp_path, timeout=1))
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        await asyncio.sleep(0.02)
        release.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("browser cancellation was not propagated")

    asyncio.run(scenario())
    assert list(tmp_path.iterdir()) == []
