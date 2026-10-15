"""A pooled aiohttp transport with bounded timeouts and cancellation."""

import asyncio
import ipaddress
from typing import Any
from urllib.parse import SplitResult, urljoin, urlsplit

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
        proxy: str | None = None,
        user_agent: str | None = None,
        cookie: str | None = None,
        local_addr: str | None = None,
    ):
        self._timeout = aiohttp.ClientTimeout(
            total=total_timeout, connect=connect_timeout, sock_read=read_timeout
        )
        self._connector: aiohttp.TCPConnector | None = None
        self._session: aiohttp.ClientSession | None = None
        self.limiter = OriginLimiter(concurrency, max_retry_wait)
        self.max_redirects = max_redirects
        self._proxy = proxy or None
        self._user_agent = user_agent or None
        self._cookie = cookie or None
        try:
            address = ipaddress.ip_address(local_addr) if local_addr else None
        except ValueError as exc:
            raise ValueError("local_addr must be an IP address") from exc
        self._local_addr = (str(address), 0) if address else None
        if self._proxy:
            parsed_proxy = urlsplit(self._proxy)
            if parsed_proxy.scheme not in {"http", "https", "socks4", "socks5"} or not parsed_proxy.hostname:
                raise ValueError("proxy must be an HTTP(S) or SOCKS URL")
            try:
                parsed_proxy.port
            except ValueError as exc:
                raise ValueError("proxy port is invalid") from exc

    @staticmethod
    def _validate_url(url: str, message: str) -> SplitResult:
        try:
            parsed = urlsplit(url)
            parsed.port
        except ValueError as exc:
            raise HttpError(ErrorCode.INVALID_REQUEST, message) from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise HttpError(ErrorCode.INVALID_REQUEST, message)
        return parsed

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            if self._connector is None or self._connector.closed:
                if self._proxy:
                    from aiohttp_socks import ProxyConnector

                    self._connector = ProxyConnector.from_url(
                        self._proxy, limit=0, local_addr=self._local_addr
                    )
                else:
                    self._connector = aiohttp.TCPConnector(limit=0, local_addr=self._local_addr)
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
        self._validate_url(
            url, "only valid HTTP(S) URLs without credentials are allowed"
        )
        headers = dict(kwargs.get("headers") or {})
        normalized_headers = {name.lower() for name in headers}
        if self._user_agent and "user-agent" not in normalized_headers:
            headers["User-Agent"] = self._user_agent
        if self._cookie and "cookie" not in normalized_headers:
            headers["Cookie"] = self._cookie
        if headers:
            kwargs["headers"] = headers
        session = await self._get_session()
        current = url
        for redirect_count in range(self.max_redirects + 1):
            try:
                semaphore = await self.limiter.acquire(current, cancel=cancel)
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
            except Exception as exc:
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
                dest = self._validate_url(destination, "unsafe redirect destination")
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
            if not 200 <= response.status < 300:
                response.release()
                semaphore.release()
                raise HttpError(ErrorCode.NETWORK_ERROR, "server returned an unsuccessful status")
            return LimitedResponse(response, semaphore)
        raise HttpError(ErrorCode.NETWORK_ERROR, "redirect limit exceeded")

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        if self._connector is not None and not self._connector.closed:
            await self._connector.close()

    async def __aenter__(self) -> "HttpRuntime":
        await self._get_session()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
