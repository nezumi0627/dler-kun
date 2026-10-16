"""Bounded HLS VOD downloader built on the shared HTTP runtime."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

from dler_kun2.domain.errors import EngineError, ErrorCode

_STREAM = re.compile(r"BANDWIDTH=(\d+)", re.I)
_URI_ATTRIBUTE = re.compile(r'URI="([^"]+)"', re.I)
_EXTENSIONS = {".aac", ".key", ".m4s", ".mp4", ".m4a", ".ts", ".vtt"}
_MAX_PLAYLIST_BYTES = 8 * 1024 * 1024
_MAX_SEGMENTS = 5000


class _Content(Protocol):
    def iter_chunked(self, size: int): ...


class _Response(Protocol):
    content: _Content

    async def text(self) -> str: ...
    def release(self) -> None: ...


class _Runtime(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> _Response: ...


ProcessRunner = Callable[..., Any]


class HlsDownloader:
    def __init__(self, runtime: _Runtime, *, ffmpeg_path: str | None = None, process_runner: ProcessRunner | None = None):
        self.runtime = runtime
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg")
        self.process_runner = process_runner or asyncio.create_subprocess_exec

    async def download(
        self,
        playlist_url: str,
        referer: str,
        output: Path,
        *,
        workers: int = 4,
        cancel: asyncio.Event | None = None,
    ) -> Path:
        if not self.ffmpeg_path:
            raise EngineError(ErrorCode.DEPENDENCY_MISSING, "ffmpeg is required for HLS media")
        if not 1 <= workers <= 8:
            raise EngineError(ErrorCode.INVALID_REQUEST, "HLS worker count must be 1..8")
        _validate_resource_url(playlist_url, playlist_url)
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary_output = output.with_name(f".{output.name}.hls-part")
        temporary_output.unlink(missing_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix=".hls-stage-", dir=output.parent) as stage_name:
                stage = Path(stage_name)
                playlist_text, playlist_base = await self._load_playlist(playlist_url, referer, cancel)
                lines, resources = self._prepare_playlist(playlist_text, playlist_base)
                await self._fetch_resources(resources, stage, referer, workers, cancel)
                local_playlist = stage / "index.m3u8"
                local_playlist.write_text("\n".join(lines) + "\n", encoding="utf-8")
                await self._mux(local_playlist, temporary_output)
            if not temporary_output.is_file() or temporary_output.stat().st_size <= 0:
                raise EngineError(ErrorCode.DOWNLOAD_FAILED, "ffmpeg produced no HLS output")
            os.replace(temporary_output, output)
            return output
        except BaseException:
            temporary_output.unlink(missing_ok=True)
            raise

    async def _load_playlist(self, url: str, referer: str, cancel: asyncio.Event | None) -> tuple[str, str]:
        text = await self._get_text(url, referer, cancel)
        if len(text.encode("utf-8")) > _MAX_PLAYLIST_BYTES or not text.lstrip("\ufeff\r\n ").startswith("#EXTM3U"):
            raise EngineError(ErrorCode.NETWORK_ERROR, "invalid HLS playlist")
        variants: list[tuple[int, str]] = []
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if line.strip().upper().startswith("#EXT-X-STREAM-INF:"):
                bandwidth_match = _STREAM.search(line)
                uri = next((candidate.strip() for candidate in lines[index + 1 :] if candidate.strip() and not candidate.lstrip().startswith("#")), None)
                if uri:
                    variants.append((int(bandwidth_match.group(1)) if bandwidth_match else 0, _resolve_url(url, uri)))
        if variants:
            _, variant_url = max(variants, key=lambda item: item[0])
            text = await self._get_text(variant_url, referer, cancel)
            if len(text.encode("utf-8")) > _MAX_PLAYLIST_BYTES or not text.lstrip("\ufeff\r\n ").startswith("#EXTM3U"):
                raise EngineError(ErrorCode.NETWORK_ERROR, "invalid HLS media playlist")
            return text, variant_url
        return text, url

    @staticmethod
    def _prepare_playlist(text: str, base_url: str) -> tuple[list[str], dict[str, str]]:
        lines: list[str] = []
        resources: dict[str, str] = {}
        segment_index = 0

        def add_resource(raw_url: str, extension: str = ".bin") -> str:
            resolved = _resolve_url(base_url, raw_url)
            if resolved not in resources:
                suffix = PurePosixPath(urlsplit(resolved).path).suffix.lower()
                if suffix not in _EXTENSIONS:
                    suffix = extension
                resources[resolved] = f"resource_{len(resources):05d}{suffix}"
            return resources[resolved]

        for line in text.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("#EXT-X-BYTERANGE") or re.search(r"\bBYTERANGE=", stripped, re.I):
                raise EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, "HLS byte-range playlists are not supported")
            if stripped.startswith("#"):
                def replace_uri(match: re.Match[str]) -> str:
                    original = match.group(1)
                    local = add_resource(original, ".key" if "#EXT-X-KEY" in stripped.upper() else ".bin")
                    return f'URI="{local}"'

                lines.append(_URI_ATTRIBUTE.sub(replace_uri, line))
                continue
            if not stripped:
                lines.append(line)
                continue
            if segment_index >= _MAX_SEGMENTS:
                raise EngineError(ErrorCode.UNSUPPORTED_CAPABILITY, "HLS playlist exceeds the 5000-segment safety limit")
            local = add_resource(stripped, ".ts")
            lines.append(local)
            segment_index += 1
        if segment_index == 0:
            raise EngineError(ErrorCode.NOT_FOUND, "HLS playlist contains no media segments")
        return lines, resources

    async def _fetch_resources(
        self,
        resources: dict[str, str],
        stage: Path,
        referer: str,
        workers: int,
        cancel: asyncio.Event | None,
    ) -> None:
        semaphore = asyncio.Semaphore(min(workers, 4))

        async def fetch(url: str, filename: str) -> None:
            async with semaphore:
                if cancel is not None and cancel.is_set():
                    raise asyncio.CancelledError
                response = await self.runtime.request("GET", url, headers={"Referer": referer}, cancel=cancel)
                target = stage / filename
                partial = target.with_suffix(target.suffix + ".part")
                try:
                    with partial.open("wb") as stream:
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            stream.write(chunk)
                        stream.flush()
                        os.fsync(stream.fileno())
                    if partial.stat().st_size == 0:
                        raise EngineError(ErrorCode.DOWNLOAD_FAILED, "HLS resource was empty")
                    os.replace(partial, target)
                except BaseException:
                    partial.unlink(missing_ok=True)
                    raise
                finally:
                    response.release()

        tasks = [asyncio.create_task(fetch(url, name)) for url, name in resources.items()]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def _get_text(self, url: str, referer: str, cancel: asyncio.Event | None) -> str:
        response = await self.runtime.request("GET", url, headers={"Referer": referer}, cancel=cancel)
        try:
            return await response.text()
        finally:
            response.release()

    async def _mux(self, playlist: Path, output: Path) -> None:
        try:
            process = await self.process_runner(
                self.ffmpeg_path,
                "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-protocol_whitelist", "file,crypto,data", "-i", str(playlist),
                "-c", "copy", "-movflags", "+faststart", "-f", "mp4", str(output),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise EngineError(ErrorCode.DEPENDENCY_MISSING, "ffmpeg executable was not found") from exc
        communicate = asyncio.create_task(process.communicate())
        try:
            _, _stderr = await asyncio.wait_for(communicate, timeout=1800)
        except asyncio.TimeoutError as exc:
            process.kill()
            await asyncio.gather(communicate, return_exceptions=True)
            raise EngineError(ErrorCode.DOWNLOAD_FAILED, "ffmpeg HLS mux timed out") from exc
        except asyncio.CancelledError:
            process.kill()
            await asyncio.gather(communicate, return_exceptions=True)
            raise
        if process.returncode != 0:
            raise EngineError(ErrorCode.DOWNLOAD_FAILED, "ffmpeg could not mux HLS media")


def _validate_resource_url(value: str, original: str) -> None:
    try:
        parsed = urlsplit(value)
        parsed.port
        source = urlsplit(original)
    except ValueError as exc:
        raise EngineError(ErrorCode.INVALID_REQUEST, "HLS playlist contains an invalid resource URL") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or (source.scheme == "https" and parsed.scheme != "https")
    ):
        raise EngineError(ErrorCode.INVALID_REQUEST, "HLS playlist contains an unsafe resource URL")


def _resolve_url(base_url: str, reference: str) -> str:
    resolved = urljoin(base_url, reference)
    _validate_resource_url(resolved, base_url)
    return resolved
