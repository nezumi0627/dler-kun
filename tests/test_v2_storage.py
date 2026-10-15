import asyncio
from pathlib import Path

import pytest

from dler_kun2.application.download import download
from dler_kun2.domain.contracts import CrawlRequest, DownloadRequest, EngineCapabilities
from dler_kun2.domain.models import CrawlResult
from dler_kun2.domain.plans import DownloadPlan
from dler_kun2.infrastructure.http.client import HttpRuntime
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

    with pytest.raises(OSError):
        asyncio.run(TransferService(Runtime()).transfer(plan("movie.mp4"), tmp_path))
    assert list(tmp_path.iterdir()) == []
