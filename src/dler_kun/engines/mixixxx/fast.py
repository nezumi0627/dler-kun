"""mixi-xxx.cc downloader.

Video pages embed a LuluStream player (luluvdo.com) that serves signed HLS.
The HLS CDN is bound to a real Chrome session (TLS fingerprint + browser
cookies) and sends no usable CORS, so segments must be fetched through the
browser's own network stack via CDP ``Network.loadNetworkResource``, which
uses Chrome's networking with the browser's cookies attached and no CORS.
"""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)
PLAY_JS = "try{jwplayer().play()}catch(e){}"

CARD_RE = re.compile(r'<div class="[^"]*(?:post|thumb|entry)[^"]*".*?</div>', re.S)
HREF_RE = re.compile(r'href="(https://mixi-xxx\.cc/[^"]+)"')
EMBED_RE = re.compile(
    r'"embedUrl"\s*:\s*"(https://(?:luluvdo|playmogo)\.com/e/[^"]+)"'
)
SLUG_RE = re.compile(r"^/([^/]+)/?$")


def fetch_html(url: str, timeout_seconds: float = 30.0) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8", "replace")


def listing_page_url(seed_url: str, page_number: int) -> str:
    if page_number <= 1:
        return seed_url
    parsed = urlparse(seed_url)
    path = parsed.path.rstrip("/")
    path = re.sub(r"/page/\d+$", "", path)
    return parsed._replace(
        path=f"{path}/page/{page_number}/", query="", fragment=""
    ).geturl()


def is_video_page_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "mixi-xxx.cc":
        return False
    match = SLUG_RE.match(parsed.path)
    if not match:
        return False
    slug = match.group(1)
    if slug.lower() in {"page", "collection"} or slug.startswith("category"):
        return False
    return len(slug) > 3


def extract_video_page_links(html: str, base_url: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for href in HREF_RE.findall(html):
        full = urljoin(base_url, href)
        if is_video_page_url(full) and full not in seen:
            seen.add(full)
            links.append(full)
    return links


def discover_video_pages(
    seed_url: str,
    max_pages: int,
    timeout_seconds: float = 30.0,
    fetcher: Callable[[str, float], str] | None = None,
) -> list[tuple[str, str]]:
    fetcher = fetcher or fetch_html
    pages: dict[str, str] = {}
    for page_number in range(1, max(1, max_pages) + 1):
        page_url = listing_page_url(seed_url, page_number)
        html = fetcher(page_url, timeout_seconds)
        for link in extract_video_page_links(html, page_url):
            slug = SLUG_RE.match(urlparse(link).path)
            title = unquote(slug.group(1)) if slug else link
            pages.setdefault(link, title)
    return list(pages.items())


def extract_embed_url(video_page_html: str) -> str | None:
    match = EMBED_RE.search(video_page_html)
    if match:
        return match.group(1)
    return None


class MixiSession:
    """One headless Chrome session that resolves and downloads LuluStream HLS.

    The browser is launched once and reused across videos; each embed
    navigation produces a fresh signed m3u8, then all segments are pulled via
    CDP ``Network.loadNetworkResource`` (browser TLS + cookies, no CORS).
    """

    def __init__(
        self,
        browser_path: str | None = None,
        timeout_seconds: float = 60.0,
        ffmpeg_path: str | None = None,
    ) -> None:
        self.browser_path = browser_path
        self.timeout_seconds = timeout_seconds
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg")
        self._proc = None
        self._client = None
        self._user_data_dir: tempfile.TemporaryDirectory | None = None
        self._frame: str | None = None
        self._headers: dict[str, str] | None = None

    def __enter__(self) -> MixiSession:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def open(self) -> None:
        from importlib import import_module

        network_media = import_module(
            "dler_kun.engines.85xo.xo_dler.network_media"
        )
        DevToolsClient = network_media.DevToolsClient
        NetworkCaptureConfig = network_media.NetworkCaptureConfig
        find_browser = network_media.find_browser
        find_free_port = network_media.find_free_port
        start_browser = network_media.start_browser
        wait_for_page_ws_url = network_media.wait_for_page_ws_url

        self.browser_path = self.browser_path or find_browser()
        if not self.browser_path:
            raise OSError("Chrome/Edge not found; set browser_path or install Chrome")
        self._user_data_dir = tempfile.TemporaryDirectory(prefix="mixixxx-")
        port = find_free_port()
        config = NetworkCaptureConfig(
            timeout_seconds=self.timeout_seconds,
            user_agent=USER_AGENT,
            browser_path=self.browser_path,
        )
        self._proc = start_browser(
            self.browser_path, port, self._user_data_dir.name, config
        )
        ws_url = wait_for_page_ws_url(port, 20)
        if ws_url is None:
            raise OSError("browser debugging endpoint did not start")
        self._client = DevToolsClient(ws_url)
        self._client.__enter__()
        self._client.call("Network.enable")
        self._client.call("Page.enable")
        self._client.call("Runtime.enable")

    def close(self) -> None:
        from importlib import import_module

        network_media = import_module(
            "dler_kun.engines.85xo.xo_dler.network_media"
        )
        stop_browser = network_media.stop_browser

        if self._client is not None:
            self._client.__exit__(None, None, None)
            self._client = None
        if self._proc is not None:
            try:
                stop_browser(self._proc)
            except Exception:
                pass
            self._proc = None
        if self._user_data_dir is not None:
            try:
                self._user_data_dir.cleanup()
            except Exception:
                pass
            self._user_data_dir = None

    def _call(self, method: str, params: dict | None = None) -> dict:
        if self._client is None:
            raise OSError("session not open")
        return self._client.call(method, params or {})

    def _call_long(
        self, method: str, params: dict | None = None, timeout: float = 60.0
    ) -> dict:
        """CDP call with a generous timeout; media fetches can exceed 5s."""
        if self._client is None:
            raise OSError("session not open")
        message_id = self._client.send(method, params or {})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self._client.recv_json(timeout=0.5)
            if message and message.get("id") == message_id:
                return message
        raise TimeoutError(f"CDP command timed out: {method}")

    def _ensure_frame(self) -> None:
        if self._frame:
            return
        tree = self._call("Page.getFrameTree").get("result", {}).get("frameTree", {})
        self._frame = tree.get("frame", {}).get("id")

    def _ensure_headers(self) -> None:
        if self._headers:
            return
        cookies = (
            self._call("Network.getCookies", {"urls": ["https://luluvdo.com"]})
            .get("result", {})
            .get("cookies", [])
        )
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        self._headers = {
            "Referer": "https://luluvdo.com/",
            "User-Agent": USER_AGENT,
            "Cookie": cookie_str,
            "Accept": "*/*",
        }

    def _capture_m3u8(self, embed_url: str) -> str | None:
        video_id = embed_url.rstrip("/").rsplit("/", 1)[-1]
        if self._client is None:
            raise OSError("session not open")
        self._client.send("Page.navigate", {"url": embed_url})
        deadline = time.monotonic() + self.timeout_seconds
        last_play = 0.0
        while time.monotonic() < deadline:
            if time.monotonic() - last_play > 3:
                last_play = time.monotonic()
                self._client.send("Runtime.evaluate", {"expression": PLAY_JS})
            msg = self._client.recv_json(timeout=0.3)
            if msg is None:
                continue
            method = msg.get("method")
            params = msg.get("params", {})
            if method == "Network.requestWillBeSent":
                url = params.get("request", {}).get("url", "")
                if ".m3u8" in url and video_id in url:
                    # Stop playback so the player's segment stream doesn't
                    # flood the CDP socket / compete with our downloads.
                    self._client.send(
                        "Runtime.evaluate",
                        {"expression": "try{jwplayer().pause()}catch(e){}"},
                    )
                    return url
        return None

    def _lnr_params(self, url: str) -> dict:
        return {
            "url": url,
            "frameId": self._frame,
            "options": {
                "disableCache": False,
                "includeCredentials": True,
                "headers": self._headers,
            },
            "maxResourceBufferSize": 30000000,
        }

    def _read_stream(self, handle: str) -> bytes:
        chunks: list[bytes] = []
        while True:
            read = self._call_long(
                "IO.read", {"handle": handle, "size": 65536}
            ).get("result", {})
            if read.get("base64Encoded"):
                chunks.append(base64.b64decode(read.get("data", "")))
            elif read.get("data"):
                chunks.append(read.get("data", "").encode("utf-8", "replace"))
            if read.get("eof"):
                break
        return b"".join(chunks)

    def _load_resource(self, url: str) -> tuple[int | None, bytes]:
        self._ensure_frame()
        self._ensure_headers()
        response = self._call_long("Network.loadNetworkResource", self._lnr_params(url))
        resource = response.get("result", {}).get("resource", {})
        handle = resource.get("stream")
        status = resource.get("httpStatusCode")
        if handle:
            try:
                body = self._read_stream(handle)
                self._call_long("IO.close", {"handle": handle}, timeout=10)
                return status, body
            except Exception:
                try:
                    self._call_long("IO.close", {"handle": handle}, timeout=10)
                except Exception:
                    pass
                raise
        return status, b""

    def _load_resource_many(
        self,
        urls: list[str],
        concurrency: int = 4,
        timeout: float = 120.0,
    ) -> dict[str, tuple[int | None, bytes]]:
        """Fetch URLs through the browser's network stack, `concurrency` at a time.

        loadNetworkResource requests are dispatched together and the browser
        downloads them concurrently, so segment transfer (the dominant cost) is
        no longer serialized to one connection.
        """
        if self._client is None:
            raise OSError("session not open")
        self._ensure_frame()
        self._ensure_headers()
        results: dict[str, tuple[int | None, bytes]] = {}
        concurrency = max(1, concurrency)
        for start in range(0, len(urls), concurrency):
            batch = urls[start : start + concurrency]
            url_by_id: dict[int, str] = {}
            for url in batch:
                message_id = self._client.send(
                    "Network.loadNetworkResource", self._lnr_params(url)
                )
                url_by_id[message_id] = url
            responses: dict[int, dict] = {}
            pending = set(url_by_id)
            deadline = time.monotonic() + timeout
            while pending and time.monotonic() < deadline:
                message = self._client.recv_json(timeout=0.5)
                if message and message.get("id") in pending:
                    responses[message["id"]] = message
                    pending.discard(message["id"])
            for message_id, message in responses.items():
                url = url_by_id[message_id]
                resource = message.get("result", {}).get("resource", {})
                handle = resource.get("stream")
                status = resource.get("httpStatusCode")
                if handle:
                    try:
                        body = self._read_stream(handle)
                        self._call_long("IO.close", {"handle": handle}, timeout=10)
                    except Exception:
                        status, body = None, b""
                else:
                    body = b""
                results[url] = (status, body)
        return results

    def _resolve_segments(self, playlist_url: str) -> list[str] | None:
        status, body = self._load_resource(playlist_url)
        if status != 200 or not body:
            return None
        text = body.decode("utf-8", "replace")
        if "#EXT-X-STREAM-INF" in text:
            variant = next(
                (
                    line.strip()
                    for line in text.splitlines()
                    if line.strip() and not line.strip().startswith("#")
                ),
                None,
            )
            if variant is None:
                return None
            return self._resolve_segments(urljoin(playlist_url, variant))
        return [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def download(
        self,
        embed_url: str,
        output_path: Path,
        on_progress: Callable[[dict], None] | None = None,
        segment_concurrency: int = 4,
    ) -> Path | None:
        if not self.ffmpeg_path:
            raise OSError("ffmpeg not found; needed to mux HLS segments")
        m3u8 = self._capture_m3u8(embed_url)
        if not m3u8:
            return None
        segments = self._resolve_segments(m3u8)
        if not segments:
            return None

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix="mixi-segs-"))
        written = 0
        try:
            segment_urls = [urljoin(m3u8, segment) for segment in segments]
            fetched = self._load_resource_many(segment_urls, segment_concurrency)
            for index, url in enumerate(segment_urls):
                segment_status, data = fetched.get(url, (None, b""))
                if segment_status == 200 and data:
                    with (tmp_dir / f"seg{index:05d}.ts").open("wb") as file:
                        file.write(data)
                    written += 1
                if on_progress:
                    on_progress(
                        {
                            "phase": "download",
                            "current_file": output_path.name,
                            "progress": round((index + 1) / len(segments) * 100, 1),
                        }
                    )
            if written == 0:
                return None
            list_file = tmp_dir / "list.txt"
            list_file.write_text(
                "\n".join(
                    f"file '{tmp_dir / f'seg{i:05d}.ts'}'" for i in range(written)
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    self.ffmpeg_path,
                    "-y",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(list_file),
                    "-c",
                    "copy",
                    str(output_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if completed.returncode != 0 or not (
                output_path.exists() and output_path.stat().st_size > 0
            ):
                return None
            return output_path
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
