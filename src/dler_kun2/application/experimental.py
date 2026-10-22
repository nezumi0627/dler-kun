"""Heuristic, explicitly labeled fallback for direct and embedded media URLs."""

from __future__ import annotations

import ipaddress
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.domain.models import DownloadResult
from dler_kun2.domain.plans import DownloadPlan
from dler_kun2.domain.types import EngineOptions
from dler_kun2.routing.registry import EngineRegistry

from .download import TransferService

_VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".m3u8"}
_MAX_PAGE_BYTES = 4 * 1024 * 1024
_URL_PATTERN = re.compile(r"(?:https?:)?//[^\s\"'<>\\]+|(?:/|\./)[^\s\"'<>\\]+")


class _MediaTags(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if tag in {"video", "source"} and values.get("src"):
            self.urls.append(values["src"])
        if tag == "meta" and values.get("property", "").lower() in {
            "og:video", "og:video:url", "og:video:secure_url",
        }:
            self.urls.append(values.get("content", ""))
        if tag == "meta" and values.get("name", "").lower() == "twitter:player:stream":
            self.urls.append(values.get("content", ""))


def _media_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or host is None or parsed.username is not None or parsed.password is not None:
            return False
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            normalized_host = host.rstrip(".").lower()
            if "." not in normalized_host or normalized_host.endswith((".localhost", ".local", ".internal")):
                return False
        return Path(parsed.path.lower()).suffix in _VIDEO_EXTENSIONS
    except ValueError:
        return False


async def _page_candidates(url: str, registry: EngineRegistry) -> list[str]:
    runtime = registry.http_runtime
    if runtime is None:
        return []
    response = await runtime.request("GET", url, headers={"Range": f"bytes=0-{_MAX_PAGE_BYTES - 1}"})
    try:
        content_type = str(response.headers.get("Content-Type", "")).lower()
        if not any(kind in content_type for kind in ("text/html", "application/xhtml")):
            return []
        body = bytearray()
        async for chunk in response.content.iter_chunked(64 * 1024):
            body.extend(chunk)
            if len(body) > _MAX_PAGE_BYTES:
                del body[_MAX_PAGE_BYTES:]
                break
        html = body.decode("utf-8", errors="replace")
    finally:
        response.release()

    parser = _MediaTags()
    parser.feed(html)
    raw_candidates = parser.urls + [
        match.group(0) for match in _URL_PATTERN.finditer(html.replace("\\/", "/"))
    ]
    candidates: list[str] = []
    for raw in raw_candidates:
        candidate = unescape(raw).strip().rstrip(",);]")
        if candidate.startswith("//"):
            candidate = f"https:{candidate}"
        else:
            candidate = urljoin(url, candidate)
        if _media_url(candidate) and candidate not in candidates:
            candidates.append(candidate)
    return candidates


async def experimental_download(
    url: str,
    output_dir: Path,
    registry: EngineRegistry,
    transfer: TransferService | None,
    options: EngineOptions | None = None,
) -> DownloadResult:
    settings = options or {}
    if transfer is None:
        return DownloadResult(requested=1, errors=(EngineError(ErrorCode.DEPENDENCY_MISSING, "experimental transfer is unavailable"),), experimental=True)
    try:
        candidates = [url] if _media_url(url) else await _page_candidates(url, registry)
        if candidates:
            # A URL ending in .mp4 may still serve an HTML landing page.
            embedded = await _page_candidates(candidates[0], registry)
            if embedded:
                candidates = embedded
        if not candidates:
            return DownloadResult(requested=1, errors=(EngineError(ErrorCode.UNSUPPORTED_SERVICE, "experimental analysis found no direct video URL"),), experimental=True)
        media_url = candidates[0]
        path_part = urlsplit(media_url).path
        filename = Path(path_part).name or "experimental-video.mp4"
        suffix = Path(filename).suffix.lower()
        plan = DownloadPlan(
            media_url=media_url,
            source_url=url,
            source_page=url,
            media_kind="hls" if suffix == ".m3u8" else "video",
            suggested_name=filename,
            size=None,
        )
        path = await transfer.transfer(
            plan,
            output_dir,
            force=bool(settings.get("force") or settings.get("overwrite")),
            metadata=bool(settings.get("metadata")),
            options=settings,
        )
        return DownloadResult(output_paths=(path,), requested=1, discovered=1, completed=1, experimental=True)
    except EngineError as exc:
        return DownloadResult(requested=1, errors=(exc,), experimental=True)
    except Exception as exc:
        from dler_kun2.infrastructure.http.client import HttpError

        if isinstance(exc, HttpError):
            error = EngineError(exc.code, "experimental media analysis request failed", exc.retry_after)
            return DownloadResult(requested=1, errors=(error,), experimental=True)
        return DownloadResult(requested=1, errors=(EngineError(ErrorCode.DOWNLOAD_FAILED, "experimental media analysis failed"),), experimental=True)
