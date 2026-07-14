from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class DetectionRule:
    engine_id: str
    domains: tuple[str, ...]

    def matches(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        if not host:
            return False
        return any(host == domain or host.endswith(f".{domain}") for domain in self.domains)


class ServiceDetector:
    """Small explicit URL detector. Downloader behavior stays inside engines."""

    def __init__(self, rules: list[DetectionRule] | None = None) -> None:
        self._rules = rules or [
            DetectionRule("gofile", ("gofile.io",)),
            DetectionRule("85xo", ("85xo.com",)),
            DetectionRule(
                "dl",
                (
                    "tweetfile.com",
                    "twimg-media.com",
                    "cdn1.twimg-media.com",
                ),
            ),
        ]

    def detect(self, url: str) -> str | None:
        for rule in self._rules:
            if rule.matches(url):
                return rule.engine_id
        return None

    def supported_domains(self) -> dict[str, list[str]]:
        return {rule.engine_id: list(rule.domains) for rule in self._rules}
