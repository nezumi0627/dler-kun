"""Shared asynchronous request budgets keyed by URL origin."""

import asyncio
import time
from collections import defaultdict
from urllib.parse import urlsplit

from .retry import retry_after_seconds


class RetryDeferred(RuntimeError):
    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"retry deferred for {retry_after:g} seconds")


class OriginLimiter:
    def __init__(self, concurrency: int = 4, max_wait: float = 300.0):
        if concurrency < 1 or max_wait < 0:
            raise ValueError("concurrency must be positive and max_wait nonnegative")
        self._semaphores: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(concurrency)
        )
        self._blocked_until: dict[str, float] = {}
        self.max_wait = max_wait

    @staticmethod
    def origin(url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("only absolute HTTP(S) URLs are allowed")
        port = parsed.port
        default = 80 if parsed.scheme == "http" else 443
        return f"{parsed.scheme}://{parsed.hostname.lower()}:{port or default}"

    async def acquire(self, url: str) -> asyncio.Semaphore:
        origin = self.origin(url)
        semaphore = self._semaphores[origin]
        await semaphore.acquire()
        wait = self._blocked_until.get(origin, 0.0) - time.monotonic()
        if wait > 0:
            if wait > self.max_wait:
                semaphore.release()
                raise RetryDeferred(wait)
            await asyncio.sleep(wait)
        return semaphore

    def defer(self, url: str, retry_after: str | None) -> float | None:
        seconds = retry_after_seconds(retry_after)
        if seconds is None:
            return None
        origin = self.origin(url)
        if seconds > self.max_wait:
            raise RetryDeferred(seconds)
        self._blocked_until[origin] = max(
            self._blocked_until.get(origin, 0.0), time.monotonic() + seconds
        )
        return seconds
