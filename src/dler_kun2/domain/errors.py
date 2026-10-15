"""Engine-independent failures exposed to application services."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite


class ErrorCode(str, Enum):
    UNSUPPORTED_SERVICE = "unsupported_service"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    AUTH_REQUIRED = "auth_required"
    NETWORK_ERROR = "network_error"
    DOWNLOAD_FAILED = "download_failed"
    CRAWL_FAILED = "crawl_failed"
    DEPENDENCY_MISSING = "dependency_missing"
    RATE_LIMITED = "rate_limited"
    AMBIGUOUS_SERVICE = "ambiguous_service"


@dataclass(eq=False)
class EngineError(Exception):
    code: ErrorCode
    message: str
    retry_after: float | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)
        if self.retry_after is not None and (
            not isfinite(self.retry_after) or self.retry_after < 0
        ):
            raise ValueError("retry_after must be finite and nonnegative")

    def to_dict(self) -> dict[str, str | float | None]:
        return {
            "code": self.code.value,
            "message": self.message,
            "retry_after": self.retry_after,
        }
