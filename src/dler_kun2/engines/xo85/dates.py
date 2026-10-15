"""Parse the relative and absolute dates used by 85po listings."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_RELATIVE = (
    (re.compile(r"(\d+)\s*(?:分|分钟)前|(\d+)\s*minutes?\s+ago", re.I), "minutes"),
    (re.compile(r"(\d+)\s*(?:時間|小时|小時)前|(\d+)\s*hours?\s+ago", re.I), "hours"),
    (re.compile(r"(\d+)\s*(?:日|天)前|(\d+)\s*days?\s+ago|(\d+)\s*ngày trước|(\d+)\s*ngay truoc", re.I), "days"),
    (re.compile(r"(\d+)\s*(?:週間|星期)前|(\d+)\s*weeks?\s+ago", re.I), "weeks"),
)
_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def parse_date(text: str, now: datetime) -> datetime | None:
    value = " ".join(text.split()).translate(_DIGITS)
    if any(token in value.lower() for token in ("today", "今日", "今天")):
        return now
    if any(token in value.lower() for token in ("yesterday", "昨日", "昨天")):
        return now - timedelta(days=1)
    for pattern, unit in _RELATIVE:
        match = pattern.search(value)
        if match:
            amount = int(next(group for group in match.groups() if group is not None))
            return now - timedelta(**{unit: amount})
    for token in re.findall(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", value):
        normalized = token.replace("/", "-").replace(".", "-")
        try:
            parsed = datetime.strptime(normalized, "%Y-%m-%d")
        except ValueError:
            continue
        return parsed.replace(tzinfo=now.tzinfo or timezone.utc)
    return None


def within_days(value: datetime | None, days: int, now: datetime) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=now.tzinfo or timezone.utc)
    return now - timedelta(days=days) <= value <= now + timedelta(minutes=5)
