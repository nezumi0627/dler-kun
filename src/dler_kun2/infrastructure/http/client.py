"""A pooled aiohttp transport with bounded timeouts and cancellation."""

import asyncio
from typing import Any
from urllib.parse import urljoin, urlsplit

import aiohttp

from dler_kun2.domain.errors import ErrorCode

from .limits import OriginLimiter, RetryDeferred


class HttpError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str, retry_after: float | None = None):
        self.code = code
        self.retry_after = retry_after
        super().__init__(message)


class LimitedResponse:
    """Response facade that keeps an origin slot until the body is released."""

    def __init__(self, response: aiohttp.ClientResponse, semaphore: asyncio.Semaphore):
        self._response = response
        self._semaphore = semaphore
        self._released = False

    @property
    def status(self) -> int:
        return self._response.status

    @property
    def headers(self):
        return self._response.headers

    @property
    def content(self):
        return self._response.content

    async def text(self, *args, **kwargs):
        try:
            return await self._response.text(*args, **kwargs)
        finally:
            self.release()

    async def json(self, *args, **kwargs):
        try:
            return await self._response.json(*args, **kwargs)
        finally:
            self.release()

    async def read(self):
        try:
            return await self._response.read()
        finally:
            self.release()

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._response.release()
            self._semaphore.release()


class HttpRuntime:
    def __init__(
        self,
        *,
        total_timeout: float = 60.0,
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
        concurrency: int = 4,
        max_retry_wait: float = 300.0,
        max_redirects: int = 10,
    ):
        self._timeout = aiohttp.ClientTimeout(
            total=total_timeout, connect=connect_timeout, sock_read=read_timeout
        )
        self._connector = aiohttp.TCPConnector(limit=0)
        self._session: aiohttp.ClientSession | None = None
        self.limiter = OriginLimiter(concurrency, max_retry_wait)
        self.max_redirects = max_redirects

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout, connector=self._connector
            )
        return self._session

    async def request(
        self,
        method: str,
        url: str,
        *,
        cancel: asyncio.Event | None = None,
        **kwargs: Any,
    ) -> LimitedResponse:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise HttpError(ErrorCode.INVALID_REQUEST, "only HTTP(S) URLs without credentials are allowed")
        session = await self._get_session()
        current = url
        for redirect_count in range(self.max_redirects + 1):
            try:
                semaphore = await self.limiter.acquire(current)
            except RetryDeferred as exc:
                raise HttpError(
                    ErrorCode.RATE_LIMITED, "origin retry window exceeds configured maximum", exc.retry_after
                ) from exc
            request_task = asyncio.create_task(
                session.request(method, current, allow_redirects=False, **kwargs)
            )
            cancel_task = asyncio.create_task(cancel.wait()) if cancel else None
            try:
                if cancel_task is None:
                    response = await request_task
                else:
                    done, _ = await asyncio.wait(
                        (request_task, cancel_task), return_when=asyncio.FIRST_COMPLETED
                    )
                    if cancel_task in done and cancel is not None and cancel.is_set():
                        request_task.cancel()
                        raise asyncio.CancelledError
                    response = request_task.result()
            except asyncio.CancelledError:
                request_task.cancel()
                semaphore.release()
                raise
            except (aiohttp.ClientError, TimeoutError) as exc:
                semaphore.release()
                raise HttpError(ErrorCode.NETWORK_ERROR, "HTTP request failed") from exc
            finally:
                if cancel_task is not None:
                    cancel_task.cancel()
            if response.status == 429:
                try:
                    delay = self.limiter.defer(current, response.headers.get("Retry-After"))
                except RetryDeferred as exc:
                    delay = exc.retry_after
                response.release()
                semaphore.release()
                raise HttpError(ErrorCode.RATE_LIMITED, "server rate limit reached", delay)
            if response.status in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                response.release()
                semaphore.release()
                if not location or redirect_count == self.max_redirects:
                    raise HttpError(ErrorCode.NETWORK_ERROR, "invalid or excessive redirect")
                destination = urljoin(current, location)
                dest = urlsplit(destination)
                if dest.scheme not in {"http", "https"} or not dest.hostname or dest.username:
                    raise HttpError(ErrorCode.INVALID_REQUEST, "unsafe redirect destination")
                if urlsplit(current).scheme == "https" and dest.scheme != "https":
                    raise HttpError(ErrorCode.INVALID_REQUEST, "HTTPS redirect cannot downgrade to HTTP")
                if self.limiter.origin(current) != self.limiter.origin(destination):
                    headers = dict(kwargs.get("headers", {}))
                    kwargs["headers"] = {
                        name: value
                        for name, value in headers.items()
                        if name.lower()
                        not in {"authorization", "cookie", "proxy-authorization"}
                    }
                    for key in ("auth", "cookies", "proxy_auth"):
                        kwargs.pop(key, None)
                current = destination
                continue
            if response.status == 404:
                response.release()
                semaphore.release()
                raise HttpError(ErrorCode.NOT_FOUND, "resource not found")
            if response.status in {401, 403}:
                response.release()
                semaphore.release()
                raise HttpError(ErrorCode.AUTH_REQUIRED, "server requires authorization")
            return LimitedResponse(response, semaphore)
        raise HttpError(ErrorCode.NETWORK_ERROR, "redirect limit exceeded")

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        if not self._connector.closed:
            await self._connector.close()

    async def __aenter__(self) -> "HttpRuntime":
        await self._get_session()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
