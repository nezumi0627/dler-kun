"""Unified curl wrapper shared by engines.

Consolidates the curl invocations that used to live separately in the mvfile
HLS downloader and the 85xo fast downloader: header injection, source-interface
binding (``local_addr``, e.g. iPhone USB tethering), DoH-based ``--resolve``
for hosts with poisoned local DNS, stall detection and optional hard time cap.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Observed working Cloudflare anycast for vid.fun800.click when local DNS
# returns a poisoned/non-TLS endpoint.
FALLBACK_IPS: dict[str, tuple[str, ...]] = {
    "vid.fun800.click": ("104.21.27.12", "172.67.140.77"),
}

_DOH_ENDPOINTS = (
    "https://cloudflare-dns.com/dns-query?name={host}&type=A",
    "https://dns.google/resolve?name={host}&type=A",
)


class CurlDownloadError(OSError):
    """A curl transfer failed (non-zero exit or empty output)."""


class CurlCancelled(CurlDownloadError):
    """The transfer was interrupted by a stop_event (user cancellation)."""


def find_curl() -> str:
    path = shutil.which("curl") or shutil.which("curl.exe")
    if not path:
        raise CurlDownloadError("dependency_missing: curl")
    return path


def build_curl_command(
    url: str,
    output_path: str | Path,
    *,
    curl_path: str | None = None,
    headers: dict[str, str] | None = None,
    local_addr: str = "",
    proxy: str = "",
    doh_host: str | None = None,
    connect_timeout_seconds: float = 10.0,
    read_timeout_seconds: float = 30.0,
    max_time_seconds: float | None = None,
    resume: bool = False,
) -> list[str]:
    curl = curl_path or find_curl()
    speed_time = max(10, int(read_timeout_seconds))
    command = [curl, "--fail", "--location", "--silent", "--show-error"]
    if resume:
        command += ["--continue-at", "-"]
    command += [
        "--connect-timeout",
        str(max(1, int(connect_timeout_seconds))),
        "--speed-limit",
        "1024",
        "--speed-time",
        str(speed_time),
        "--output",
        str(output_path),
    ]
    if max_time_seconds is not None and max_time_seconds > 0:
        command += ["--max-time", str(int(max_time_seconds))]
    if local_addr:
        command += ["--interface", local_addr]
    if proxy:
        command += ["--proxy", proxy]
    if doh_host:
        command += curl_resolve_args(doh_host)
    for key, value in (headers or {}).items():
        command += ["--header", f"{key}: {value}"]
    command += ["--", url]
    return command


def curl_download(
    url: str,
    output_path: str | Path,
    *,
    curl_path: str | None = None,
    headers: dict[str, str] | None = None,
    local_addr: str = "",
    proxy: str = "",
    doh_host: str | None = None,
    connect_timeout_seconds: float = 10.0,
    read_timeout_seconds: float = 30.0,
    max_time_seconds: float | None = None,
    resume: bool = False,
    stop_event: threading.Event | None = None,
) -> None:
    """Download ``url`` to ``output_path``; raise :class:`CurlDownloadError` on failure."""
    command = build_curl_command(
        url,
        output_path,
        curl_path=curl_path,
        headers=headers,
        local_addr=local_addr,
        proxy=proxy,
        doh_host=doh_host,
        connect_timeout_seconds=connect_timeout_seconds,
        read_timeout_seconds=read_timeout_seconds,
        max_time_seconds=max_time_seconds,
        resume=resume,
    )
    proc = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stderr_chunks: list[str] = []

    def _drain_stderr() -> None:
        if proc.stderr:
            stderr_chunks.append(proc.stderr.read())

    drain = threading.Thread(target=_drain_stderr, daemon=True)
    drain.start()
    while proc.poll() is None:
        if stop_event is not None and stop_event.is_set():
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise CurlCancelled("interrupted by user")
        time.sleep(0.25)
    drain.join(timeout=1.0)
    out = Path(output_path)
    if proc.returncode != 0 or not out.exists() or out.stat().st_size <= 0:
        detail = "".join(stderr_chunks).strip()
        raise CurlDownloadError(detail or f"curl exit {proc.returncode}")


def fetch_text(
    url: str,
    *,
    curl_path: str | None = None,
    headers: dict[str, str] | None = None,
    local_addr: str = "",
    proxy: str = "",
    timeout_seconds: float = 30.0,
) -> str:
    """Fetch ``url`` and return the response body as text (for page scraping)."""
    curl = curl_path or find_curl()
    command = [curl, "--fail", "--location", "--silent", "--show-error"]
    if local_addr:
        command += ["--interface", local_addr]
    if proxy:
        command += ["--proxy", proxy]
    for key, value in (headers or {}).items():
        command += ["--header", f"{key}: {value}"]
    command += ["--", url]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip()
        raise CurlDownloadError(detail or f"curl exit {completed.returncode}")
    return completed.stdout


@lru_cache(maxsize=32)
def resolve_ipv4(host: str, timeout_seconds: float = 5.0) -> tuple[str, ...]:
    """Return IPv4 addresses for host via DoH, with static fallbacks."""
    host = host.lower().strip()
    answers: list[str] = []
    for template in _DOH_ENDPOINTS:
        try:
            request = Request(
                template.format(host=host),
                headers={
                    "Accept": "application/dns-json",
                    "User-Agent": "dler-kun",
                },
            )
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
            for item in payload.get("Answer") or []:
                if int(item.get("type") or 0) != 1:
                    continue
                data = str(item.get("data") or "").strip()
                if _is_ipv4(data) and data not in answers:
                    answers.append(data)
            if answers:
                return tuple(answers)
        except OSError:
            continue
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    fallback = FALLBACK_IPS.get(host)
    if fallback:
        return fallback
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return ()
    for info in infos:
        ip = str(info[4][0])
        if _is_ipv4(ip) and ip not in answers:
            answers.append(ip)
    return tuple(answers)


def curl_resolve_args(host: str, port: int = 443) -> list[str]:
    ips = resolve_ipv4(host)
    if not ips:
        return []
    return ["--resolve", f"{host}:{port}:{ips[0]}"]


def _is_ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(part) <= 255 for part in parts)
    except ValueError:
        return False


__all__ = [
    "CurlCancelled",
    "CurlDownloadError",
    "FALLBACK_IPS",
    "build_curl_command",
    "curl_download",
    "curl_resolve_args",
    "fetch_text",
    "find_curl",
    "resolve_ipv4",
]
