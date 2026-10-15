"""Managed Chrome DevTools capture for the site's browser-bound HLS player."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


class BrowserCaptureError(RuntimeError):
    pass


class _Cdp:
    def __init__(self, url: str, timeout: float):
        try:
            from websockets.sync.client import connect
        except ImportError as exc:
            raise BrowserCaptureError("websockets package is required for browser capture") from exc
        self.socket = connect(url, open_timeout=timeout, close_timeout=2, max_size=32 * 1024 * 1024)
        self.sequence = 0

    def close(self):
        self.socket.close()

    def send(self, method: str, params: dict | None = None) -> int:
        self.sequence += 1
        self.socket.send(json.dumps({"id": self.sequence, "method": method, "params": params or {}}, separators=(",", ":")))
        return self.sequence

    def call(self, method: str, params: dict | None = None, timeout: float = 15) -> dict:
        command_id = self.send(method, params)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = json.loads(self.socket.recv(timeout=min(0.5, deadline - time.monotonic())))
            except TimeoutError:
                continue
            if message.get("id") == command_id:
                if "error" in message:
                    raise BrowserCaptureError("Chrome DevTools command failed")
                return message.get("result", {})
        raise BrowserCaptureError("Chrome DevTools command timed out")


class BrowserHlsDownloader:
    def __init__(self, *, browser_path: str | None = None, ffmpeg_path: str | None = None, timeout: float = 60):
        self.browser_path = browser_path or _find_browser()
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg")
        self.timeout = timeout

    def download(self, embed_url: str, output: Path, *, concurrency: int = 4) -> Path:
        if not self.browser_path:
            raise BrowserCaptureError("Chrome or Edge is required for mixi-xxx playback")
        if not self.ffmpeg_path:
            raise BrowserCaptureError("ffmpeg is required to mux the HLS stream")
        if concurrency < 1 or concurrency > 16:
            raise BrowserCaptureError("segment concurrency must be between 1 and 16")
        parsed = urlsplit(embed_url)
        if parsed.scheme != "https" or parsed.hostname not in {"luluvdo.com", "luluvido.com", "playmogo.com"}:
            raise BrowserCaptureError("unsupported embed provider")
        with tempfile.TemporaryDirectory(prefix="dler-kun2-mixi-browser-") as temp:
            root = Path(temp)
            port = _free_port()
            process = subprocess.Popen(
                [self.browser_path, "--headless=new", "--disable-gpu", "--mute-audio", "--no-first-run", "--disable-extensions", "--remote-allow-origins=*", f"--remote-debugging-port={port}", f"--user-data-dir={root / 'profile'}", "about:blank"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            cdp = None
            try:
                ws_url = _page_websocket(port, self.timeout)
                cdp = _Cdp(ws_url, self.timeout)
                cdp.call("Page.enable")
                cdp.call("Network.enable")
                cdp.call("Runtime.enable")
                frame_id = cdp.call("Page.getFrameTree").get("frameTree", {}).get("frame", {}).get("id")
                if not frame_id:
                    raise BrowserCaptureError("Chrome player frame is missing")
                cdp.send("Page.navigate", {"url": embed_url})
                playlist = _capture_playlist(cdp, embed_url, self.timeout)
                if not playlist:
                    raise BrowserCaptureError("HLS playlist was not observed")
                headers = _cookie_headers(cdp, embed_url)
                segments = _playlist_segments(cdp, playlist, frame_id, headers, self.timeout)
                if not segments:
                    raise BrowserCaptureError("HLS playlist contains no media segments")
                fetched = _load_many(cdp, segments, frame_id, headers, concurrency, self.timeout)
                segment_paths = []
                for index, segment_url in enumerate(segments):
                    status, body = fetched.get(segment_url, (None, b""))
                    if status == 200 and body:
                        segment_path = root / f"segment-{index:06d}.ts"
                        segment_path.write_bytes(body)
                        segment_paths.append(segment_path)
                if not segment_paths:
                    raise BrowserCaptureError("no HLS segments could be downloaded")
                concat = root / "segments.txt"
                concat.write_text("\n".join(f"file '{path.as_posix()}'" for path in segment_paths), encoding="utf-8")
                output.parent.mkdir(parents=True, exist_ok=True)
                completed = subprocess.run([self.ffmpeg_path, "-y", "-nostdin", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(output)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=self.timeout * 3, check=False)
                if completed.returncode or not output.is_file() or output.stat().st_size == 0:
                    raise BrowserCaptureError("ffmpeg could not mux downloaded HLS segments")
                return output
            finally:
                if cdp is not None:
                    cdp.close()
                _stop(process)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _page_websocket(port: int, timeout: float) -> str:
    deadline = time.monotonic() + min(timeout, 30)
    while time.monotonic() < deadline:
        try:
            request = Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
            with urlopen(request, timeout=2) as response:
                page = json.loads(response.read())
            if isinstance(page, dict) and isinstance(page.get("webSocketDebuggerUrl"), str):
                return page["webSocketDebuggerUrl"]
        except (OSError, ValueError):
            time.sleep(0.2)
    raise BrowserCaptureError("Chrome DevTools endpoint did not start")


def _capture_playlist(cdp: _Cdp, embed_url: str, timeout: float) -> str | None:
    deadline = time.monotonic() + timeout
    next_play = 0.0
    while time.monotonic() < deadline:
        if time.monotonic() >= next_play:
            cdp.send("Runtime.evaluate", {"expression": "try{jwplayer().play()}catch(e){}"})
            next_play = time.monotonic() + 2
        try:
            event = json.loads(cdp.socket.recv(timeout=0.3))
        except TimeoutError:
            continue
        if event.get("method") == "Network.requestWillBeSent":
            url = event.get("params", {}).get("request", {}).get("url", "")
            if ".m3u8" in url.lower() and urlsplit(url).hostname:
                cdp.send("Runtime.evaluate", {"expression": "try{jwplayer().pause()}catch(e){}"})
                return url
    return None


def _cookie_headers(cdp: _Cdp, embed_url: str) -> dict[str, str]:
    del cdp
    # The browser attaches cookies for each target origin through includeCredentials.
    # Never copy embed-site cookies into a header sent to a different CDN host.
    return {"Referer": embed_url, "Accept": "*/*", "User-Agent": "Mozilla/5.0"}


def _load_resource(cdp: _Cdp, url: str, frame_id: str, headers: dict[str, str], timeout: float) -> tuple[int | None, bytes]:
    response = cdp.call("Network.loadNetworkResource", {"url": url, "frameId": frame_id, "options": {"includeCredentials": True, "headers": headers, "disableCache": False}}, timeout)
    resource = response.get("resource", {})
    handle = resource.get("stream")
    status = resource.get("httpStatusCode")
    chunks = []
    while handle:
        chunk = cdp.call("IO.read", {"handle": handle, "size": 65536}, timeout)
        data = chunk.get("data", "")
        if chunk.get("base64Encoded"):
            import base64
            chunks.append(base64.b64decode(data))
        else:
            chunks.append(data.encode())
        if chunk.get("eof"):
            break
    if handle:
        cdp.call("IO.close", {"handle": handle}, timeout=5)
    return status if isinstance(status, int) else None, b"".join(chunks)


def _playlist_segments(cdp: _Cdp, playlist: str, frame_id: str, headers: dict[str, str], timeout: float) -> list[str]:
    status, body = _load_resource(cdp, playlist, frame_id, headers, timeout)
    if status != 200:
        return []
    lines = [line.strip() for line in body.decode("utf-8", "replace").splitlines() if line.strip()]
    if any(line.startswith("#EXT-X-KEY") and "METHOD=NONE" not in line for line in lines):
        raise BrowserCaptureError("encrypted HLS playlists are not supported")
    if "#EXT-X-STREAM-INF" in body.decode("utf-8", "replace"):
        variants = []
        bandwidth = 0
        pending = False
        for line in lines:
            if line.startswith("#EXT-X-STREAM-INF"):
                match = __import__("re").search(r"BANDWIDTH=(\d+)", line)
                bandwidth = int(match.group(1)) if match else 0
                pending = True
            elif pending and not line.startswith("#"):
                variants.append((bandwidth, urljoin(playlist, line)))
                pending = False
        return _playlist_segments(cdp, max(variants)[1], frame_id, headers, timeout) if variants else []
    return [urljoin(playlist, line) for line in lines if not line.startswith("#")]


def _load_many(cdp: _Cdp, urls: list[str], frame_id: str, headers: dict[str, str], concurrency: int, timeout: float) -> dict[str, tuple[int | None, bytes]]:
    result = {}
    for start in range(0, len(urls), concurrency):
        batch = urls[start : start + concurrency]
        commands = {cdp.send("Network.loadNetworkResource", {"url": url, "frameId": frame_id, "options": {"includeCredentials": True, "headers": headers, "disableCache": False}}): url for url in batch}
        deadline = time.monotonic() + timeout
        responses = {}
        pending = set(commands)
        while pending and time.monotonic() < deadline:
            try:
                message = json.loads(cdp.socket.recv(timeout=0.5))
            except TimeoutError:
                continue
            if message.get("id") in pending:
                responses[message["id"]] = message.get("result", {})
                pending.remove(message["id"])
        for command_id, url in commands.items():
            resource = responses.get(command_id, {}).get("resource", {})
            handle = resource.get("stream")
            chunks = []
            while handle:
                try:
                    chunk = cdp.call("IO.read", {"handle": handle, "size": 65536}, timeout)
                except BrowserCaptureError:
                    break
                data = chunk.get("data", "")
                if chunk.get("base64Encoded"):
                    import base64
                    chunks.append(base64.b64decode(data))
                else:
                    chunks.append(data.encode())
                if chunk.get("eof"):
                    break
            if handle:
                try:
                    cdp.call("IO.close", {"handle": handle}, timeout=5)
                except BrowserCaptureError:
                    pass
            status = resource.get("httpStatusCode")
            result[url] = (status if isinstance(status, int) else None, b"".join(chunks))
    return result


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _find_browser() -> str | None:
    for name in ("chrome", "msedge", "google-chrome", "chromium"):
        path = shutil.which(name)
        if path:
            return path
    if os.name == "nt":
        for path in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
            if Path(path).is_file():
                return path
    return None
