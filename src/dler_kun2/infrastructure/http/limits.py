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

    async def acquire(
        self, url: str, cancel: asyncio.Event | None = None
    ) -> asyncio.Semaphore:
        origin = self.origin(url)
        semaphore = self._semaphores[origin]
        acquired = False
        cancel_task = None
        acquire_task = None
        try:
            if cancel is not None and cancel.is_set():
                raise asyncio.CancelledError
            if cancel is None:
                await semaphore.acquire()
            else:
                acquire_task = asyncio.create_task(semaphore.acquire())
                cancel_task = asyncio.create_task(cancel.wait())
                done, _ = await asyncio.wait(
                    (acquire_task, cancel_task), return_when=asyncio.FIRST_COMPLETED
                )
                if cancel_task in done and cancel.is_set():
                    if acquire_task.done() and not acquire_task.cancelled():
                        acquired = True
                    else:
                        acquire_task.cancel()
                    raise asyncio.CancelledError
                acquire_task.result()
            acquired = True
            wait = self._blocked_until.get(origin, 0.0) - time.monotonic()
            if wait > 0:
                if wait > self.max_wait:
                    raise RetryDeferred(wait)
                if cancel is None:
                    await asyncio.sleep(wait)
                else:
                    try:
                        await asyncio.wait_for(cancel.wait(), timeout=wait)
                    except TimeoutError:
                        pass
                    if cancel.is_set():
                        raise asyncio.CancelledError
            return semaphore
        except BaseException:
            if acquire_task is not None and not acquire_task.done():
                acquire_task.cancel()
            if (
                not acquired
                and acquire_task is not None
                and acquire_task.done()
                and not acquire_task.cancelled()
            ):
                acquired = True
            if acquired:
                semaphore.release()
            raise
        finally:
            if cancel_task is not None:
                cancel_task.cancel()

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
