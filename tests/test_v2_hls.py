import asyncio
from pathlib import Path
from typing import Any, cast

from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.infrastructure.storage.hls import HlsDownloader
from dler_kun2.infrastructure.storage.hls import _Response as HlsResponse


class _Content:
    def __init__(self, value: bytes):
        self.value = value

    async def iter_chunked(self, _size):
        yield self.value


class _Response:
    def __init__(self, value: bytes):
        self.value = value
        self.content = _Content(value)

    async def text(self):
        return self.value.decode()

    def release(self):
        pass


class _Runtime:
    def __init__(self, resources):
        self.resources = resources
        self.calls = []

    async def request(self, method: str, url: str, **kwargs: Any) -> HlsResponse:
        self.calls.append((method, url, kwargs))
        if url not in self.resources:
            raise AssertionError(f"unexpected HLS resource: {url}")
        return cast(HlsResponse, _Response(self.resources[url]))


def test_hls_download_fetches_best_variant_and_rewrites_local_playlist(tmp_path):
    master = b"""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=100
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=900
high/index.m3u8
"""
    media = b"""#EXTM3U
#EXT-X-TARGETDURATION:5
#EXTINF:5,
seg-1.ts?sig=secret
#EXTINF:5,
seg-2.ts?sig=secret
#EXT-X-ENDLIST
"""
    runtime = _Runtime({
        "https://media.test/master.m3u8": master,
        "https://media.test/high/index.m3u8": media,
        "https://media.test/high/seg-1.ts?sig=secret": b"one",
        "https://media.test/high/seg-2.ts?sig=secret": b"two",
    })
    commands = []

    class Process:
        returncode = 0

        async def communicate(self):
            playlist = Path(commands[-1][commands[-1].index("-i") + 1])
            content = playlist.read_text(encoding="utf-8")
            assert "resource_00000.ts" in content and "resource_00001.ts" in content
            assert "sig=secret" not in content
            target = Path(commands[-1][-1])
            target.write_bytes(b"muxed mp4")
            return b"", b""

    async def runner(*command, **_kwargs):
        commands.append(command)
        return Process()

    async def scenario():
        output = tmp_path / "result.mp4"
        downloader = HlsDownloader(runtime, ffmpeg_path="ffmpeg", process_runner=runner)
        await downloader.download("https://media.test/master.m3u8", "https://share.test/item", output)
        assert output.read_bytes() == b"muxed mp4"
        assert {url for _, url, _ in runtime.calls} == {
            "https://media.test/master.m3u8",
            "https://media.test/high/index.m3u8",
            "https://media.test/high/seg-1.ts?sig=secret",
            "https://media.test/high/seg-2.ts?sig=secret",
        }
        assert all(call[2]["headers"]["Referer"] == "https://share.test/item" for call in runtime.calls)
        assert list(tmp_path.iterdir()) == [output]

    asyncio.run(scenario())


def test_hls_rejects_byte_range_instead_of_corrupting_output(tmp_path):
    runtime = _Runtime({
        "https://media.test/list.m3u8": b"#EXTM3U\n#EXT-X-BYTERANGE:10@0\nseg.ts\n#EXT-X-ENDLIST\n"
    })

    async def scenario():
        downloader = HlsDownloader(runtime, ffmpeg_path="ffmpeg", process_runner=None)
        try:
            await downloader.download("https://media.test/list.m3u8", "https://share.test/item", tmp_path / "x.mp4")
        except EngineError as exc:
            assert exc.code is ErrorCode.UNSUPPORTED_CAPABILITY
        else:
            raise AssertionError("byte ranges must not be silently misinterpreted")
        assert not list(tmp_path.iterdir())

    asyncio.run(scenario())


def test_hls_playlist_body_is_size_limited(tmp_path):
    class StreamingContent:
        async def iter_chunked(self, _size):
            yield b"#EXTM3U\n"
            yield b"x" * (8 * 1024 * 1024 + 1)

    class StreamingResponse:
        content = StreamingContent()

        async def text(self):
            raise AssertionError("bounded playlist reader must use streaming")

        def release(self):
            pass

    class Runtime:
        async def request(self, method: str, url: str, **kwargs: Any) -> HlsResponse:
            del method, url, kwargs
            return cast(HlsResponse, StreamingResponse())

    runtime = Runtime()

    async def scenario():
        downloader = HlsDownloader(runtime, ffmpeg_path="ffmpeg")
        try:
            await downloader.download("https://media.test/list.m3u8", "https://share.test/item", tmp_path / "x.mp4")
        except EngineError as exc:
            assert exc.code is ErrorCode.NETWORK_ERROR
        else:
            raise AssertionError("oversized playlist must be rejected")
        assert not list(tmp_path.iterdir())

    asyncio.run(scenario())
