"""Atomic file transfer helpers."""

import os
from collections.abc import AsyncIterable
from pathlib import Path


class TransferService:
    def __init__(self, runtime, allocator=None):
        self.runtime = runtime
        if allocator is None:
            from .paths import OutputAllocator

            allocator = OutputAllocator()
        self.allocator = allocator

    async def write_chunks(self, chunks: AsyncIterable[bytes], output: Path) -> Path:
        output = Path(output)
        part = Path(f"{output}.part")
        try:
            with part.open("wb") as stream:
                async for chunk in chunks:
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(part, output)
            return output
        except BaseException:
            part.unlink(missing_ok=True)
            raise

    async def transfer(self, plan, output_dir: Path) -> Path:
        output = self.allocator.reserve(plan, output_dir)
        response = None
        try:
            response = await self.runtime.request("GET", plan.media_url)

            async def chunks():
                async for chunk in response.content.iter_chunked(64 * 1024):
                    yield chunk

            await self.write_chunks(chunks(), output)
        except BaseException as exc:
            output.unlink(missing_ok=True)
            Path(f"{output}.part").unlink(missing_ok=True)
            from dler_kun2.infrastructure.http.client import HttpError

            if isinstance(exc, HttpError):
                from dler_kun2.domain.errors import EngineError

                raise EngineError(exc.code, "media transfer request failed", exc.retry_after) from exc
            raise
        finally:
            if response is not None:
                response.release()
        return output
