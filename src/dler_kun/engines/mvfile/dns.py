from __future__ import annotations

import json
import socket
from functools import lru_cache
from urllib.request import Request, urlopen

# Observed working Cloudflare anycast for vid.fun800.click when local DNS
# returns a poisoned/non-TLS endpoint.
FALLBACK_IPS: dict[str, tuple[str, ...]] = {
    "vid.fun800.click": ("104.21.27.12", "172.67.140.77"),
}

_DOH_ENDPOINTS = (
    "https://cloudflare-dns.com/dns-query?name={host}&type=A",
    "https://dns.google/resolve?name={host}&type=A",
)


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
                    "User-Agent": "dler-kun/mvfile",
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
        ip = info[4][0]
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
