from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class DetectionRule:
    engine_id: str
    domains: tuple[str, ...]
    exact: bool = False

    def matches(self, url: str) -> bool:
        host = _normalized_host(url)
        if not host:
            return False
        if self.exact:
            return host in self.domains
        return any(
            host == domain or host.endswith(f".{domain}") for domain in self.domains
        )


class ServiceDetector:
    """Small explicit URL detector. Downloader behavior stays inside engines."""

    def __init__(self, rules: list[DetectionRule] | None = None) -> None:
        self._rules = rules or [
            DetectionRule(
                "gofile",
                ("gofile.io", "gofile-douga.com", "gofilelab.com"),
            ),
            DetectionRule("gofilerun", ("gofile.run",)),
            DetectionRule("85xo", ("85xo.com", "85po.net", "85po.com")),
            DetectionRule(
                "mvfile",
                (
                    "mvfile.com",
                    "file-photo.com",
                    "tweetfile.com",
                    "gofile.website",
                    "image-share.cc",
                    "tweetplay.com",
                    "imagedist.com",
                    "gofile.rocks",
                    "gofile.host",
                    "gofile.guru",
                    "gofile.name",
                    "mediasplayer.com",
                    "twimg-media.com",
                    "media-twimg.com",
                    "twimg.jp",
                    "video.twimg.jp",
                    "video.twimg-image.com",
                    "video.twimg1.com",
                ),
            ),
            DetectionRule(
                "twimg",
                (
                    "twimg-media.com",
                    "cdn1.twimg-media.com",
                    "tweetfile.com",
                    "twimg.jp",
                ),
                exact=True,
            ),
            DetectionRule("videy", ("video.twimg.news", "videy.co")),
            DetectionRule("mixixxx", ("mixi-xxx.cc",)),
        ]

    def detect(self, url: str) -> str | None:
        for rule in self._rules:
            if rule.matches(url):
                return rule.engine_id
        return None

    def supported_domains(self) -> dict[str, list[str]]:
        return {rule.engine_id: list(rule.domains) for rule in self._rules}


def _normalized_host(url: str) -> str:
    value = url.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if not parsed.netloc and "://" not in value:
        parsed = urlparse(f"https://{value}")
    return (parsed.hostname or "").lower()
