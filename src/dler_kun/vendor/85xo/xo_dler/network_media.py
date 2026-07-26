from __future__ import annotations

import base64
import json
import os
import random
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .models import MediaItem


MEDIA_EXTENSIONS = (
    ".mp4",
    ".webm",
    ".mov",
    ".m4v",
    ".mkv",
    ".avi",
)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)
VIDEO_PAGE_PATTERN = "/v/"
NETWORK_MEDIA_MARKERS = ("/get_file/", "remote_control.php")
SCREENSHOT_PATTERN = re.compile(r"/contents/videos_screenshots/\d+/(?P<video_id>\d+)/")


@dataclass(frozen=True)
class NetworkCaptureConfig:
    timeout_seconds: float = 15.0
    user_agent: str = DEFAULT_USER_AGENT
    browser_path: str | None = None


def capture_video_ids(
    seed_url: str, config: NetworkCaptureConfig, page_count: int
) -> list[str]:
    page_count = max(page_count, 1)
    browser_path = find_browser(config.browser_path)
    if browser_path is None:
        print("[warn] browser not found; network video discovery skipped")
        return []
    print(f"[scan] browser: {browser_path}")

    with tempfile.TemporaryDirectory(prefix="xo-dler-browser-") as user_data_dir:
        port = find_free_port()
        process = start_browser(browser_path, port, user_data_dir, config)
        try:
            ws_url = wait_for_page_ws_url(port, config.timeout_seconds)
            if ws_url is None:
                print("[warn] browser debugging endpoint did not start")
                return []
            return capture_listing_video_ids(
                ws_url, seed_url, config.timeout_seconds, page_count
            )
        finally:
            stop_browser(process)


def capture_media_items(page_url: str, config: NetworkCaptureConfig) -> list[MediaItem]:
    browser_path = find_browser(config.browser_path)
    if browser_path is None:
        print("[warn] browser not found; network media capture skipped")
        return []

    with tempfile.TemporaryDirectory(prefix="xo-dler-browser-") as user_data_dir:
        port = find_free_port()
        process = start_browser(browser_path, port, user_data_dir, config)
        try:
            ws_url = wait_for_page_ws_url(port, config.timeout_seconds)
            if ws_url is None:
                print("[warn] browser debugging endpoint did not start")
                return []
            return capture_page_media(ws_url, page_url, config.timeout_seconds)
        finally:
            stop_browser(process)


def start_browser(
    browser_path: str,
    port: int,
    user_data_dir: str,
    config: NetworkCaptureConfig,
) -> subprocess.Popen:
    return subprocess.Popen(
        [
            browser_path,
            "--headless=new",
            "--disable-gpu",
            "--mute-audio",
            "--no-first-run",
            "--disable-extensions",
            "--window-size=1280,720",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            f"--user-agent={config.user_agent}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_browser(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def capture_listing_video_ids(
    ws_url: str,
    seed_url: str,
    timeout_seconds: float,
    page_count: int,
) -> list[str]:
    video_ids: list[str] = []
    empty_pages = 0
    with DevToolsClient(ws_url) as client:
        client.call("Network.enable")
        client.call("Page.enable")
        for page_number in range(1, page_count + 1):
            before_count = len(set(video_ids))
            url = listing_page_url(seed_url, page_number)
            print(f"[scan] listing page {page_number}/{page_count}: {url}")
            client.call("Page.navigate", {"url": url})
            collect_listing_page_ids(client, video_ids, timeout_seconds)
            after_count = len(set(video_ids))
            print(
                f"[scan] listing page {page_number}: +{after_count - before_count} videos (total {after_count})"
            )
            if after_count == before_count:
                empty_pages += 1
                if empty_pages >= 2:
                    break
            else:
                empty_pages = 0
    return dedupe(video_ids)


def collect_listing_page_ids(
    client: DevToolsClient,
    video_ids: list[str],
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    next_scroll = time.monotonic() + 1
    seen_ids = set(video_ids)
    initial_count = len(seen_ids)
    last_event_at = time.monotonic()
    last_new_id_at = time.monotonic()
    while time.monotonic() < deadline:
        message = client.recv_json(timeout=0.25)
        if message is not None:
            last_event_at = time.monotonic()
            url = network_event_url(message)
            video_id = video_id_from_screenshot_url(url)
            if video_id is not None and video_id not in seen_ids:
                seen_ids.add(video_id)
                video_ids.append(video_id)
                last_new_id_at = time.monotonic()

        if time.monotonic() >= next_scroll:
            next_scroll = time.monotonic() + 1
            client.send(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseWheel",
                    "x": 640,
                    "y": 360,
                    "deltaX": 0,
                    "deltaY": 900,
                },
            )
        if (
            len(seen_ids) > initial_count
            and time.monotonic() - last_new_id_at > 2
            and time.monotonic() - last_event_at > 1
        ):
            break


def listing_page_url(seed_url: str, page_number: int) -> str:
    if page_number <= 1:
        return seed_url
    parsed = urlparse(seed_url)
    base_path = parsed.path.rstrip("/")
    path = f"{base_path}/{page_number}/"
    return parsed._replace(path=path, query="", fragment="").geturl()


def capture_page_media(
    ws_url: str, page_url: str, timeout_seconds: float
) -> list[MediaItem]:
    media_candidates: dict[str, datetime | None] = {}
    video_candidates: dict[str, datetime | None] = {}
    deadline = time.monotonic() + timeout_seconds
    last_event_at = time.monotonic()
    last_media_at = time.monotonic()
    with DevToolsClient(ws_url) as client:
        client.call("Network.enable")
        client.call("Page.enable")
        client.call("Page.navigate", {"url": page_url})

        clicked_play = False
        while time.monotonic() < deadline:
            message = client.recv_json(timeout=0.5)
            if message is None:
                continue
            last_event_at = time.monotonic()
            method = message.get("method")
            params = message.get("params", {})
            if method == "Network.requestWillBeSent":
                url = params.get("request", {}).get("url", "")
                if is_network_media_url(url):
                    media_candidates.setdefault(url, None)
                    last_media_at = time.monotonic()
            elif method == "Network.responseReceived":
                response = params.get("response", {})
                url = response.get("url", "")
                mime_type = response.get("mimeType", "")
                if is_network_media_response(url, mime_type):
                    last_media_at = time.monotonic()
                    published_at = published_at_from_headers(
                        response.get("headers", {})
                    )
                    if "video/" in mime_type.lower():
                        video_candidates[url] = published_at
                    else:
                        media_candidates[url] = published_at
                    redirect_url = response.get("headers", {}).get(
                        "location"
                    ) or response.get("headers", {}).get("Location")
                    if redirect_url and is_network_media_url(redirect_url):
                        media_candidates.setdefault(redirect_url, published_at)

            if not clicked_play and time.monotonic() + 3 < deadline:
                clicked_play = True
                click_viewport_center(client)
            if (
                video_candidates
                and time.monotonic() - last_media_at > 2
                and time.monotonic() - last_event_at > 1
            ):
                break

    items = []
    candidates = video_candidates or media_candidates
    for url, published_at in candidates.items():
        items.append(
            MediaItem(url=url, source_page=page_url, published_at=published_at)
        )
    return items


def click_viewport_center(client: DevToolsClient) -> None:
    for event_type in ("mousePressed", "mouseReleased"):
        client.send(
            "Input.dispatchMouseEvent",
            {
                "type": event_type,
                "x": 640,
                "y": 360,
                "button": "left",
                "clickCount": 1,
            },
        )


def network_event_url(message: dict) -> str:
    method = message.get("method")
    params = message.get("params", {})
    if method == "Network.requestWillBeSent":
        return params.get("request", {}).get("url", "")
    if method == "Network.responseReceived":
        return params.get("response", {}).get("url", "")
    return ""


def video_id_from_screenshot_url(url: str) -> str | None:
    match = SCREENSHOT_PATTERN.search(url)
    if match:
        return match.group("video_id")
    return None


def video_page_url(seed_url: str, video_id: str) -> str:
    parsed = urlparse(seed_url)
    return parsed._replace(path=f"/v/{video_id}/", query="", fragment="").geturl()


def is_video_page_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and VIDEO_PAGE_PATTERN in parsed.path


def is_network_media_url(url: str) -> bool:
    lowered = url.lower()
    return is_media_url(url) or any(
        marker in lowered for marker in NETWORK_MEDIA_MARKERS
    )


def is_network_media_response(url: str, mime_type: str) -> bool:
    return "video/" in mime_type.lower() or is_network_media_url(url)


def is_media_url(value: str) -> bool:
    path = urlparse(value).path.lower().rstrip("/")
    return any(path.endswith(extension) for extension in MEDIA_EXTENSIONS)


def published_at_from_headers(headers: dict) -> datetime | None:
    last_modified = header_value(headers, "last-modified")
    if not last_modified:
        return None
    try:
        return parsedate_to_datetime(last_modified)
    except (TypeError, ValueError):
        return None


def header_value(headers: dict, name: str) -> str | None:
    normalized = name.lower()
    for key, value in headers.items():
        if str(key).lower() == normalized:
            return str(value)
    return None


def dedupe(values: list[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def find_browser(explicit_path: str | None = None) -> str | None:
    candidates = [
        explicit_path,
        os.environ.get("XO_DLER_BROWSER"),
        shutil.which("chrome"),
        shutil.which("chrome.exe"),
        shutil.which("msedge"),
        shutil.which("msedge.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_page_ws_url(port: int, timeout_seconds: float) -> str | None:
    deadline = time.monotonic() + timeout_seconds
    new_page_url = f"http://127.0.0.1:{port}/json/new?{quote('about:blank')}"
    list_url = f"http://127.0.0.1:{port}/json/list"
    while time.monotonic() < deadline:
        page_ws_url = first_page_ws_url(list_url)
        if page_ws_url:
            return page_ws_url

        try:
            request = Request(new_page_url, method="PUT")
            with urlopen(request, timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return payload["webSocketDebuggerUrl"]
        except Exception:
            time.sleep(0.2)
    return None


def first_page_ws_url(list_url: str) -> str | None:
    try:
        with urlopen(list_url, timeout=1) as response:
            pages = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    for page in pages:
        if page.get("type") == "page" and page.get("webSocketDebuggerUrl"):
            return page["webSocketDebuggerUrl"]
    return None


class DevToolsClient:
    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self.sock: socket.socket | None = None
        self.next_id = 1

    def __enter__(self) -> DevToolsClient:
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.sock is not None:
            self.sock.close()

    def connect(self) -> None:
        parsed = urlparse(self.ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query}"
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        sock = socket.create_connection((host, port), timeout=5)
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = sock.recv(4096)
        if b" 101 " not in response:
            raise OSError("websocket upgrade failed")
        self.sock = sock

    def call(self, method: str, params: dict | None = None) -> dict:
        message_id = self.send(method, params)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            message = self.recv_json(timeout=0.5)
            if message and message.get("id") == message_id:
                return message
        raise TimeoutError(f"CDP command timed out: {method}")

    def send(self, method: str, params: dict | None = None) -> int:
        message_id = self.next_id
        self.next_id += 1
        payload = {"id": message_id, "method": method, "params": params or {}}
        self.send_frame(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        return message_id

    def send_frame(self, payload: bytes) -> None:
        if self.sock is None:
            raise OSError("websocket is not connected")
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = random.randbytes(4) if hasattr(random, "randbytes") else os.urandom(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_json(self, timeout: float) -> dict | None:
        if self.sock is None:
            raise OSError("websocket is not connected")
        self.sock.settimeout(timeout)
        try:
            opcode, payload = self.recv_frame()
        except socket.timeout:
            return None
        if opcode == 1:
            return json.loads(payload.decode("utf-8"))
        if opcode == 8:
            return None
        if opcode == 9:
            self.send_pong(payload)
        return None

    def recv_frame(self) -> tuple[int, bytes]:
        if self.sock is None:
            raise OSError("websocket is not connected")
        header = self.recv_exact(2)
        opcode = header[0] & 0x0F
        masked = bool(header[1] & 0x80)
        length = header[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self.recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self.recv_exact(8))[0]
        mask = self.recv_exact(4) if masked else b""
        payload = self.recv_exact(length)
        if masked:
            payload = bytes(
                value ^ mask[index % 4] for index, value in enumerate(payload)
            )
        return opcode, payload

    def recv_exact(self, size: int) -> bytes:
        if self.sock is None:
            raise OSError("websocket is not connected")
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self.sock.recv(size - len(chunks))
            if not chunk:
                raise OSError("websocket closed")
            chunks.extend(chunk)
        return bytes(chunks)

    def send_pong(self, payload: bytes) -> None:
        if self.sock is None:
            return
        header = bytearray([0x8A])
        header.append(0x80 | len(payload))
        mask = os.urandom(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)
