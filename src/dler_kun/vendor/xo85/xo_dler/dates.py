from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


_RELATIVE_DAYS_PATTERNS = [
    re.compile(r"(?P<days>\d+)\s*日前"),
    re.compile(r"(?P<days>\d+)\s*天前"),
    re.compile(r"(?P<days>\d+)\s*days?\s+ago", re.IGNORECASE),
]

_RELATIVE_WEEKS_PATTERNS = [
    re.compile(r"(?P<weeks>\d+)\s*週間前"),
    re.compile(r"(?P<weeks>\d+)\s*星期前"),
    re.compile(r"(?P<weeks>\d+)\s*weeks?\s+ago", re.IGNORECASE),
]

_ABSOLUTE_PATTERNS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
]


def parse_published_at(text: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(timezone.utc)
    normalized = " ".join(text.split())

    if (
        "今日" in normalized
        or "今天" in normalized
        or re.search(r"\btoday\b", normalized, re.IGNORECASE)
    ):
        return now
    if (
        "昨日" in normalized
        or "昨天" in normalized
        or re.search(r"\byesterday\b", normalized, re.IGNORECASE)
    ):
        return now - timedelta(days=1)

    for pattern in _RELATIVE_DAYS_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return now - timedelta(days=int(match.group("days")))

    for pattern in _RELATIVE_WEEKS_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return now - timedelta(weeks=int(match.group("weeks")))

    for absolute_format in _ABSOLUTE_PATTERNS:
        for token in normalized.split():
            try:
                parsed = datetime.strptime(token, absolute_format)
            except ValueError:
                continue
            return parsed.replace(tzinfo=now.tzinfo)

    return None


def is_within_days(
    value: datetime | None, days: int, now: datetime | None = None
) -> bool:
    if value is None:
        return False

    now = now or datetime.now(value.tzinfo or timezone.utc)
    if value.tzinfo is None and now.tzinfo is not None:
        value = value.replace(tzinfo=now.tzinfo)

    return now - timedelta(days=days) <= value <= now + timedelta(minutes=5)
