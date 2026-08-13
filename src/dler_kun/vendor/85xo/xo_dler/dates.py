from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


_RELATIVE_DAYS_PATTERNS = [
    re.compile(r"(?P<days>\d+)\s*日前"),
    re.compile(r"(?P<days>\d+)\s*天前"),
    re.compile(r"(?P<days>\d+)\s*days?\s+ago", re.IGNORECASE),
    re.compile(r"(?P<days>\d+)\s*ngày trước", re.IGNORECASE),
    re.compile(r"(?P<days>\d+)\s*ngay truoc", re.IGNORECASE),
]

_RELATIVE_WEEKS_PATTERNS = [
    re.compile(r"(?P<weeks>\d+)\s*週間前"),
    re.compile(r"(?P<weeks>\d+)\s*星期前"),
    re.compile(r"(?P<weeks>\d+)\s*weeks?\s+ago", re.IGNORECASE),
    re.compile(r"(?P<weeks>\d+)\s*tuần trước", re.IGNORECASE),
    re.compile(r"(?P<weeks>\d+)\s*tuan truoc", re.IGNORECASE),
]

_RELATIVE_MONTHS_PATTERNS = [
    re.compile(r"(?P<months>\d+)\s*ヶ月前"),
    re.compile(r"(?P<months>\d+)\s*か月前"),
    re.compile(r"(?P<months>\d+)\s*个月前"),
    re.compile(r"(?P<months>\d+)\s*months?\s+ago", re.IGNORECASE),
    re.compile(r"(?P<months>\d+)\s*tháng trước", re.IGNORECASE),
    re.compile(r"(?P<months>\d+)\s*thang truoc", re.IGNORECASE),
]

_RELATIVE_YEARS_PATTERNS = [
    re.compile(r"(?P<years>\d+)\s*年前"),
    re.compile(r"(?P<years>\d+)\s*years?\s+ago", re.IGNORECASE),
    re.compile(r"(?P<years>\d+)\s*năm trước", re.IGNORECASE),
    re.compile(r"(?P<years>\d+)\s*nam truoc", re.IGNORECASE),
]

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")

_ABSOLUTE_PATTERNS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
]


def _normalize_date_text(text: str) -> str:
    return " ".join(text.split()).translate(_FULLWIDTH_DIGITS)


def parse_published_at(text: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(timezone.utc)
    normalized = _normalize_date_text(text)

    if (
        "今日" in normalized
        or "今天" in normalized
        or re.search(r"\b(hôm nay|hom nay)\b", normalized, re.IGNORECASE)
        or re.search(r"\btoday\b", normalized, re.IGNORECASE)
    ):
        return now
    if (
        "昨日" in normalized
        or "昨天" in normalized
        or re.search(r"\b(hôm qua|hom qua)\b", normalized, re.IGNORECASE)
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

    for pattern in _RELATIVE_MONTHS_PATTERNS:
        match = pattern.search(normalized)
        if match:
            # A month is not a fixed span; 30 days is close enough for a
            # freshness window. ponytail: calendar-accurate months if the
            # boundary around --days 30 matters.
            return now - timedelta(days=int(match.group("months")) * 30)

    for pattern in _RELATIVE_YEARS_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return now - timedelta(days=int(match.group("years")) * 365)

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
