import asyncio
import json
from pathlib import Path

import pytest

from dler_kun2.application.download import download
from dler_kun2.domain.contracts import CrawlRequest, DownloadRequest, EngineCapabilities
from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import CrawlResult
from dler_kun2.domain.plans import DownloadPlan
from dler_kun2.infrastructure.http.client import HttpError, HttpRuntime
from dler_kun2.infrastructure.storage.cache import JsonCache
from dler_kun2.infrastructure.storage.paths import OutputAllocator
from dler_kun2.infrastructure.storage.transfer import TransferService
from dler_kun2.routing.registry import EngineRegistry
from dler_kun2.routing.rules import RouteRule


def plan(name: str, url: str = "https://cdn.example/a") -> DownloadPlan:
    return DownloadPlan(url, url, "https://site.example/", "video", name, None)


@pytest.mark.parametrize("name", ["../outside.mp4", "C:\\outside.mp4", "CON.txt", "a/b.mp4"])
def test_allocator_contains_untrusted_names(tmp_path, name):
    path = OutputAllocator().reserve(plan(name), tmp_path)
    assert path.resolve().parent == tmp_path.resolve()


def test_allocator_disambiguates_casefold_and_url_identity(tmp_path):
    allocator = OutputAllocator()
    first = allocator.reserve(plan("Clip.mp4", "https://cdn.example/one"), tmp_path)
    second = allocator.reserve(plan("clip.MP4", "https://cdn.example/two"), tmp_path)
    same = allocator.reserve(plan("Clip.mp4", "https://cdn.example/one"), tmp_path)
    assert len({first.name.casefold(), second.name.casefold(), same.name.casefold()}) == 3


def test_allocator_uses_item_identity_for_files_in_one_share(tmp_path):
    source = "https://gofile.io/d/SHARE"
    first = DownloadPlan("https://cdn.example/a", source, source, "video", "clip.mp4", None, {"file_id": "FILE_A"})
    second = DownloadPlan("https://cdn.example/b", source, source, "video", "clip.mp4", None, {"file_id": "FILE_B"})
    paths = [OutputAllocator().reserve(first, tmp_path), OutputAllocator().reserve(second, tmp_path)]
    assert paths[0] != paths[1]
    assert all(path.parent == tmp_path for path in paths)


def test_allocator_reserves_existing_collision(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"keep")
    path = OutputAllocator().reserve(plan("clip.mp4"), tmp_path)
    assert path != tmp_path / "clip.mp4"
    assert (tmp_path / "clip.mp4").read_bytes() == b"keep"


def test_allocator_preserves_sanitized_relative_folder_and_contains_path(tmp_path):
    item = DownloadPlan("https://cdn.example/a", "https://site.example/", "https://site.example/", "video", "clip.mp4", None, {"relative_dir": "../folder/CON"})
    path = OutputAllocator().reserve(item, tmp_path)
    assert path.resolve().is_relative_to(tmp_path.resolve())
    assert tmp_path.resolve() in path.resolve().parents
    assert path.parent.name == "_CON"


def test_transfer_writes_part_then_atomically_completes(tmp_path):
    async def chunks():
        yield b"hello"

    output = tmp_path / "clip.mp4"
    asyncio.run(TransferService(object()).write_chunks(chunks(), output))
    assert output.read_bytes() == b"hello"
    assert not Path(str(output) + ".part").exists()


def test_transfer_injects_into_application_download(tmp_path):
    class Engine:
        engine_id = "sample"
        capabilities = EngineCapabilities(download=True)

        async def resolve_download(self, request: DownloadRequest):
            return plan("movie.mp4")

        async def crawl(self, request: CrawlRequest) -> CrawlResult:
            return CrawlResult()

        async def ranking(self, request: CrawlRequest) -> CrawlResult:
            return CrawlResult()

    class Response:
        class Content:
            async def iter_chunked(self, _size):
                yield b"movie"

        content = Content()

        def release(self):
            pass

    class Runtime:
        async def request(self, _method, _url):
            return Response()

    registry = EngineRegistry()
    registry.register(Engine(), [RouteRule("sample", ("site.example",))])
    transfer = TransferService(Runtime())
    result = asyncio.run(download("https://site.example/a", tmp_path, registry, transfer))
    assert result.completed == 1
    assert result.output_paths[0].read_bytes() == b"movie"


def test_hls_transfer_uses_hls_downloader_not_direct_playlist_body(tmp_path):
    class Runtime:
        async def request(self, *_args, **_kwargs):
            raise AssertionError("HLS media must not be saved as a direct response")

    class Hls:
        async def download(self, url, referer, output, *, workers, cancel=None):
            assert "/master.m3u8?sig=" in url
            assert referer == "https://site.example/item"
            assert workers == 3
            output.write_bytes(b"real mp4")
            return output

    item = DownloadPlan(
        "https://cdn.example/master.m3u8?sig=private",
        "https://site.example/item",
        "https://site.example/item",
        "hls",
        "clip.mp4",
        100,
    )
    output = asyncio.run(
        TransferService(Runtime(), hls_downloader=Hls()).transfer(
            item, tmp_path, options={"segment_concurrency": 3}
        )
    )
    assert output.read_bytes() == b"real mp4"


def test_failed_http_status_leaves_no_reserved_output(tmp_path):
    async def scenario():
        from aiohttp import web
        from aiohttp.test_utils import TestServer

        async def failed(_request):
            return web.Response(status=503, text="not media")

        app = web.Application()
        app.router.add_get("/", failed)
        server = TestServer(app)
        await server.start_server()
        runtime = HttpRuntime()
        item = plan("movie.mp4", str(server.make_url("/")))
        try:
            with pytest.raises(Exception):
                await TransferService(runtime).transfer(item, tmp_path)
            assert list(tmp_path.iterdir()) == []
        finally:
            await runtime.close()
            await server.close()

    asyncio.run(scenario())


def test_transfer_normalizes_http_errors_and_preserves_retry_after(tmp_path):
    class Runtime:
        async def request(self, _method, _url):
            raise HttpError(ErrorCode.RATE_LIMITED, "private response", 15)

    with pytest.raises(EngineError) as failure:
        asyncio.run(TransferService(Runtime()).transfer(plan("clip.mp4"), tmp_path))
    assert failure.value.code is ErrorCode.RATE_LIMITED
    assert failure.value.retry_after == 15
    assert list(tmp_path.iterdir()) == []


def test_failed_stream_removes_reserved_output_and_partial_file(tmp_path):
    class Content:
        async def iter_chunked(self, _size):
            yield b"partial"
            raise OSError("stream interrupted")

    class Response:
        content = Content()

        def release(self):
            pass

    class Runtime:
        async def request(self, _method, _url):
            return Response()

    with pytest.raises(EngineError) as failure:
        asyncio.run(TransferService(Runtime()).transfer(plan("movie.mp4"), tmp_path))
    assert failure.value.code is ErrorCode.DOWNLOAD_FAILED
    assert list(tmp_path.iterdir()) == []


def test_transfer_rejects_size_mismatch_and_cleans_reserved_path(tmp_path):
    class Content:
        async def iter_chunked(self, _size):
            yield b"wrong"

    class Response:
        content = Content()

        def release(self):
            pass

    class Runtime:
        async def request(self, _method, _url):
            return Response()

    item = DownloadPlan("https://cdn.example/a", "https://site.example/a", "https://site.example/a", "video", "clip.mp4", 10)
    with pytest.raises(EngineError) as failure:
        asyncio.run(TransferService(Runtime()).transfer(item, tmp_path))
    assert failure.value.code is ErrorCode.DOWNLOAD_FAILED
    assert list(tmp_path.iterdir()) == []


def test_transfer_cache_reuses_only_verified_output_under_requested_root(tmp_path):
    class Content:
        async def iter_chunked(self, _size):
            yield b"complete"

    class Response:
        content = Content()

        def release(self):
            pass

    class Runtime:
        calls = 0

        async def request(self, _method, _url):
            self.calls += 1
            return Response()

    async def scenario():
        runtime = Runtime()
        cache = JsonCache(tmp_path / "transfer-cache.json")
        transfer = TransferService(runtime, cache=cache)
        item = plan("movie.mp4", "https://site.example/share")
        first = await transfer.transfer(item, tmp_path / "first")
        cached = await transfer.transfer(item, tmp_path / "first")
        other_item = DownloadPlan("https://cdn.example/other", item.source_url, item.source_page, "video", "movie.mp4", None)
        other = await transfer.transfer(other_item, tmp_path / "first")
        second_root = await transfer.transfer(item, tmp_path / "second")
        assert cached == first
        assert second_root != first
        assert other != first
        assert runtime.calls == 3
        return first

    first = asyncio.run(scenario())
    assert first.read_bytes() == b"complete"
    cache_text = (tmp_path / "transfer-cache.json").read_text(encoding="utf-8")
    assert "https://site.example/share" not in cache_text
    assert "signature=secret" not in cache_text
    assert "cdn.example" not in cache_text


def test_transfer_force_refetches_cached_plan_without_overwriting_existing_file(tmp_path):
    class Content:
        def __init__(self, content):
            self.content = content

        async def iter_chunked(self, _size):
            yield self.content

    class Response:
        def __init__(self, content):
            self.content = Content(content)

        def release(self):
            pass

    class Runtime:
        calls = 0

        async def request(self, _method, _url):
            self.calls += 1
            return Response(b"complete" if self.calls == 1 else b"refreshed")

    async def scenario():
        runtime = Runtime()
        transfer = TransferService(runtime, cache=JsonCache(tmp_path / "cache.json"))
        item = plan("clip.mp4", "https://site.example/item")
        first = await transfer.transfer(item, tmp_path / "output")
        refreshed = await transfer.transfer(item, tmp_path / "output", force=True)
        assert first != refreshed
        assert first.read_bytes() == b"complete"
        assert refreshed.read_bytes() == b"refreshed"
        assert runtime.calls == 2

    asyncio.run(scenario())


def test_transfer_metadata_sidecar_excludes_signed_urls_and_secret_fields(tmp_path):
    class Content:
        async def iter_chunked(self, _size):
            yield b"video"

    class Response:
        content = Content()

        def release(self):
            pass

    class Runtime:
        async def request(self, _method, _url):
            return Response()

    item = DownloadPlan(
        "https://cdn.example/clip.mp4?X-Amz-Signature=private",
        "https://site.example/share?password=private",
        "https://site.example/share?token=private",
        "video",
        "clip.mp4",
        None,
        {"file_id": "file-1", "api_token": "private", "title": "clip"},
    )
    output = asyncio.run(TransferService(Runtime()).transfer(item, tmp_path, metadata=True))
    sidecar = Path(f"{output}.json")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["metadata"] == {"file_id": "file-1", "title": "clip"}
    assert payload["source_url"] == "https://site.example/share"
    assert payload["source_page"] == "https://site.example/share"
    assert "cdn.example" not in sidecar.read_text(encoding="utf-8")
    assert "private" not in sidecar.read_text(encoding="utf-8")


def test_transfer_normalizes_output_reservation_errors(tmp_path):
    class BrokenAllocator:
        def reserve(self, _plan, _root):
            raise ValueError("private path detail")

    class Runtime:
        async def request(self, _method, _url):
            raise AssertionError("network request should not start")

    with pytest.raises(EngineError) as failure:
        asyncio.run(TransferService(Runtime(), allocator=BrokenAllocator()).transfer(plan("clip.mp4"), tmp_path))
    assert failure.value.code is ErrorCode.INVALID_REQUEST
    assert "private path detail" not in failure.value.message


def test_metadata_sidecar_normalizes_atomic_write_errors(tmp_path, monkeypatch):
    import dler_kun2.infrastructure.storage.transfer as transfer_module

    def fail_replace(_temporary, _target):
        raise OSError("private filesystem detail")

    monkeypatch.setattr(transfer_module.os, "replace", fail_replace)
    with pytest.raises(EngineError) as failure:
        transfer_module.write_metadata_sidecar(plan("clip.mp4"), tmp_path / "clip.mp4")
    assert failure.value.code is ErrorCode.DOWNLOAD_FAILED
    assert "private filesystem detail" not in failure.value.message
