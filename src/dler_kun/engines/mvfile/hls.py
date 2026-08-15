from __future__ import annotations

import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

from ...net import CurlDownloadError, USER_AGENT, curl_download

STREAM_INF_RE = re.compile(r"#EXT-X-STREAM-INF:([^\n]+)\n([^\n]+)", re.M)
BANDWIDTH_RE = re.compile(r"BANDWIDTH=(\d+)")


class MvfileDownloadError(RuntimeError):
    """Raised when HLS fetch/remux fails."""


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
    return (cleaned[:160] or "video")


def target_mp4_path(output_dir: Path, name: str) -> Path:
    stem = Path(sanitize_filename(name)).stem
    return output_dir / f"{stem}.mp4"


def download_hls_to_mp4(
    media_url: str,
    target: Path,
    *,
    referer: str,
    force: bool = False,
    timeout_seconds: float = 30.0,
    hls_workers: int = 8,
    local_addr: str = "",
    proxy: str = "",
) -> Path:
    if not media_url:
        raise MvfileDownloadError("media url missing")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise MvfileDownloadError("dependency_missing: ffmpeg")
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if not curl:
        raise MvfileDownloadError("dependency_missing: curl")

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0 and not force:
        return target

    part = target.with_suffix(target.suffix + ".part.mp4")
    # Persistent segment staging so interrupted downloads resume from saved
    # segments instead of restarting from zero. Cleaned up only on success.
    staging = target.with_name(target.stem + ".hlsd")
    staging.mkdir(parents=True, exist_ok=True)

    master_path = staging / "master.m3u8"
    _curl_download(
        curl,
        media_url,
        master_path,
        referer=referer,
        timeout_seconds=timeout_seconds,
        local_addr=local_addr,
        proxy=proxy,
    )
    master_text = master_path.read_text(encoding="utf-8", errors="replace")
    variant_url = select_best_variant(media_url, master_text)
    variant_path = staging / "index.m3u8"
    if variant_url == media_url:
        variant_path.write_text(master_text, encoding="utf-8")
        playlist_text = master_text
        playlist_base = media_url
    else:
        _curl_download(
            curl,
            variant_url,
            variant_path,
            referer=referer,
            timeout_seconds=timeout_seconds,
            local_addr=local_addr,
            proxy=proxy,
        )
        playlist_text = variant_path.read_text(encoding="utf-8", errors="replace")
        playlist_base = variant_url

    local_playlist = materialize_playlist(
        curl,
        playlist_text,
        playlist_base,
        staging,
        referer=referer,
        timeout_seconds=timeout_seconds,
        workers=max(1, hls_workers),
        local_addr=local_addr,
        proxy=proxy,
        reuse=not force,
    )
    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(local_playlist),
                "-c",
                "copy",
                str(part),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0 or not part.exists() or part.stat().st_size <= 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise MvfileDownloadError(detail or f"ffmpeg exit {completed.returncode}")
        part.replace(target)
    except BaseException:
        # Keep staging only if it has partial segments worth resuming.
        # Empty dirs (master fetch failed, e.g. media deleted) are junk.
        if not any(staging.glob("seg_*")):
            shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(staging, ignore_errors=True)
    return target


def select_best_variant(master_url: str, master_text: str) -> str:
    candidates: list[tuple[int, str]] = []
    for match in STREAM_INF_RE.finditer(master_text):
        attrs, uri = match.group(1), match.group(2).strip()
        bandwidth_match = BANDWIDTH_RE.search(attrs)
        bandwidth = int(bandwidth_match.group(1)) if bandwidth_match else 0
        candidates.append((bandwidth, urljoin(master_url, uri)))
    if not candidates:
        return master_url
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def materialize_playlist(
    curl_path: str,
    playlist_text: str,
    playlist_url: str,
    work_dir: Path,
    *,
    referer: str,
    timeout_seconds: float,
    workers: int = 8,
    local_addr: str = "",
    proxy: str = "",
    reuse: bool = False,
) -> Path:
    lines = playlist_text.splitlines()
    segments: list[tuple[str, Path]] = []
    rewritten: list[str] = []
    segment_index = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            rewritten.append(line)
            continue
        segment_url = urljoin(playlist_url, stripped)
        suffix = Path(urlparse(segment_url).path).suffix or ".ts"
        local_name = f"seg_{segment_index:05d}{suffix}"
        segment_index += 1
        segments.append((segment_url, work_dir / local_name))
        rewritten.append(local_name)

    def fetch(spec: tuple[str, Path]) -> None:
        url, path = spec
        if reuse and path.exists() and path.stat().st_size > 0:
            return
        _curl_download(
            curl_path,
            url,
            path,
            referer=referer,
            timeout_seconds=timeout_seconds,
            local_addr=local_addr,
            proxy=proxy,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(fetch, segments))

    out = work_dir / "local.m3u8"
    out.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    return out


def _origin_from_referer(referer: str) -> str:
    parsed = urlparse(referer)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "https://cdn.mvfile.com"


def _curl_download(
    curl_path: str,
    url: str,
    output_path: Path,
    *,
    referer: str,
    timeout_seconds: float,
    local_addr: str = "",
    proxy: str = "",
) -> None:
    try:
        curl_download(
            url,
            output_path,
            curl_path=curl_path,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": referer,
                "Origin": _origin_from_referer(referer),
            },
            local_addr=local_addr,
            proxy=proxy,
            # Prefer DoH-resolved IP to bypass poisoned local DNS for vid CDN.
            doh_host=urlparse(url).hostname or None,
            connect_timeout_seconds=max(5, int(timeout_seconds // 3) or 5),
            read_timeout_seconds=timeout_seconds,
            max_time_seconds=max(30, int(timeout_seconds * 20)),
        )
    except CurlDownloadError as exc:
        raise MvfileDownloadError(str(exc)) from exc
