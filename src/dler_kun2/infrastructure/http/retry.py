"""Parsing helpers for server supplied retry times."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def retry_after_seconds(value: str | None, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            reference = now or datetime.now(timezone.utc)
            if reference.tzinfo is None:
                reference = reference.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - reference).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
