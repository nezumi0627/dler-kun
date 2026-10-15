"""Atomic file transfer helpers."""

import asyncio
import hashlib
import json
import os
import tempfile
from collections.abc import AsyncIterable
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dler_kun2.domain.errors import EngineError, ErrorCode

from .cache import JsonCache

_SECRET_METADATA_PARTS = ("token", "cookie", "password", "secret", "signature", "authorization", "api_key", "apikey", "url")


def write_metadata_sidecar(plan, output: Path) -> Path:
    def public_page(value: str) -> str:
        parsed = urlsplit(value)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    metadata = {
        key: value
        for key, value in plan.metadata.items()
        if not any(part in key.lower().replace("-", "_") for part in _SECRET_METADATA_PARTS)
    }
    payload = {
        "source_url": public_page(plan.source_url),
        "source_page": public_page(plan.source_page),
        "media_kind": plan.media_kind,
        "suggested_name": plan.suggested_name,
        "size": plan.size,
        "metadata": metadata,
    }
    sidecar = Path(f"{output}.json")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{sidecar.name}.", suffix=".tmp", dir=sidecar.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, sidecar)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return sidecar


class TransferService:
    def __init__(self, runtime, allocator=None, *, cache: JsonCache | None = None):
        self.runtime = runtime
        if allocator is None:
            from .paths import OutputAllocator

            allocator = OutputAllocator()
        self.allocator = allocator
        self.cache = cache

    @staticmethod
    def _cache_key(plan) -> str:
        stable_id = plan.metadata.get("file_id")
        if isinstance(stable_id, (str, int)) and str(stable_id):
            identity = f"{plan.source_url}\0{stable_id}"
        else:
            media = urlsplit(plan.media_url)
            media_identity = f"{media.scheme.lower()}://{media.netloc.lower()}{media.path}"
            identity = f"{plan.source_url}\0{media_identity}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

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

    async def transfer(self, plan, output_dir: Path, *, force: bool = False, metadata: bool = False) -> Path:
        root = Path(output_dir).resolve()
        cache_key = self._cache_key(plan)
        if self.cache is not None and not force:
            entry = self.cache.get(cache_key)
            if entry and entry.get("status") == "complete":
                cached_path = Path(str(entry.get("path") or ""))
                try:
                    valid = (
                        cached_path.is_file()
                        and cached_path.stat().st_size > 0
                        and cached_path.stat().st_size == int(entry.get("size", -1))
                        and (plan.size is None or cached_path.stat().st_size == plan.size)
                        and cached_path.resolve().is_relative_to(root)
                    )
                except (OSError, ValueError):
                    valid = False
                if valid:
                    if metadata:
                        write_metadata_sidecar(plan, cached_path)
                    return cached_path
        output = self.allocator.reserve(plan, output_dir)
        response = None
        try:
            response = await self.runtime.request("GET", plan.media_url)

            async def chunks():
                async for chunk in response.content.iter_chunked(64 * 1024):
                    yield chunk

            await self.write_chunks(chunks(), output)
            size = output.stat().st_size
            if size <= 0 or (plan.size is not None and size != plan.size):
                raise EngineError(ErrorCode.DOWNLOAD_FAILED, "downloaded file size does not match the media plan")
            if metadata:
                write_metadata_sidecar(plan, output)
            if self.cache is not None:
                try:
                    self.cache.set(cache_key, {"status": "complete", "path": str(output), "size": size})
                except OSError:
                    pass
        except BaseException as exc:
            output.unlink(missing_ok=True)
            Path(f"{output}.part").unlink(missing_ok=True)
            from dler_kun2.infrastructure.http.client import HttpError

            if isinstance(exc, HttpError):
                raise EngineError(exc.code, "media transfer request failed", exc.retry_after) from exc
            if isinstance(exc, (EngineError, asyncio.CancelledError)):
                raise
            if isinstance(exc, Exception):
                raise EngineError(ErrorCode.DOWNLOAD_FAILED, "media transfer failed") from exc
            raise
        finally:
            if response is not None:
                response.release()
        return output
