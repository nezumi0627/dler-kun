"""Atomic file transfer helpers."""

import os
from collections.abc import AsyncIterable
from pathlib import Path


class TransferService:
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

    async def transfer(self, plan, output_dir: Path, runtime, allocator=None) -> Path:
        from .paths import OutputAllocator

        chosen = allocator or OutputAllocator()
        output = chosen.reserve(plan, output_dir)

        response = await runtime.request("GET", plan.media_url)
        try:
            async def chunks():
                async for chunk in response.content.iter_chunked(64 * 1024):
                    yield chunk

            await self.write_chunks(chunks(), output)
        finally:
            response.release()
        return output
