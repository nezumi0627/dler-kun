import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from dler_kun2.domain.errors import ErrorCode
from dler_kun2.infrastructure.http.client import HttpError, HttpRuntime
from dler_kun2.infrastructure.http.limits import OriginLimiter, RetryDeferred
from dler_kun2.infrastructure.http.retry import retry_after_seconds


def test_retry_after_parses_seconds_and_http_date():
    now = datetime.now(timezone.utc)
    assert retry_after_seconds("3", now=now) == 3
    date = format_datetime(now + timedelta(seconds=7), usegmt=True)
    assert retry_after_seconds(date, now=now) == pytest.approx(7, abs=1)


def test_origin_limiter_refuses_wait_above_cap():
    limiter = OriginLimiter(max_wait=2)
    with pytest.raises(RetryDeferred) as exc:
        limiter.defer("https://example.test/x", "10")
    assert exc.value.retry_after == pytest.approx(10, abs=0.1)
    with pytest.raises(RetryDeferred) as blocked:
        asyncio.run(limiter.acquire("https://example.test/next"))
    assert blocked.value.retry_after == pytest.approx(10, abs=0.1)


def test_origin_limiter_releases_slot_when_retry_wait_is_cancelled():
    async def scenario():
        limiter = OriginLimiter(concurrency=1)
        url = "https://example.test/item"
        limiter.defer(url, "30")
        cancel = asyncio.Event()
        task = asyncio.create_task(limiter.acquire(url, cancel=cancel))
        await asyncio.sleep(0.01)
        cancel.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.2)
        assert limiter._semaphores[limiter.origin(url)]._value == 1

    asyncio.run(scenario())


def test_origin_limiter_awaits_internal_task_cleanup_after_cancellation():
    async def scenario():
        from typing import cast

        started = asyncio.Event()
        cleanup_started = asyncio.Event()
        finish_cleanup = asyncio.Event()
        cleaned = asyncio.Event()

        class SlowSemaphore:
            async def acquire(self):
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cleanup_started.set()
                    await finish_cleanup.wait()
                    cleaned.set()
                    raise

            def release(self):
                pass

        limiter = OriginLimiter()
        url = "https://example.test/item"
        limiter._semaphores[limiter.origin(url)] = cast(asyncio.Semaphore, SlowSemaphore())
        task = asyncio.create_task(limiter.acquire(url, cancel=asyncio.Event()))
        await started.wait()
        task.cancel()
        await cleanup_started.wait()
        assert not task.done()
        finish_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()

    asyncio.run(scenario())


@pytest.mark.parametrize("url", ["https://user:pass@example.test/", "https://:pass@example.test/"])
def test_http_runtime_rejects_any_url_userinfo(url):
    async def scenario():
        runtime = HttpRuntime()
        try:
            with pytest.raises(HttpError) as exc:
                await runtime.request("GET", url)
            assert exc.value.code is ErrorCode.INVALID_REQUEST
        finally:
            await runtime.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("url", ["https://example.test:bad/", "https://example.test:99999/"])
def test_http_runtime_normalizes_invalid_initial_port(url):
    async def scenario():
        runtime = HttpRuntime()
        try:
            with pytest.raises(HttpError) as exc:
                await runtime.request("GET", url)
            assert exc.value.code is ErrorCode.INVALID_REQUEST
        finally:
            await runtime.close()

    asyncio.run(scenario())


def test_retry_after_rejects_nonfinite_values():
    assert retry_after_seconds("inf") is None
    assert retry_after_seconds("-inf") is None


def test_http_runtime_pools_and_normalizes_rate_limit():
    async def scenario():
        async def limited(_request):
            return web.Response(status=429, headers={"Retry-After": "4"})

        app = web.Application()
        app.router.add_get("/", limited)
        server = TestServer(app)
        await server.start_server()
        runtime = HttpRuntime(max_retry_wait=1)
        try:
            with pytest.raises(Exception) as exc:
                await runtime.request("GET", str(server.make_url("/")))
            assert getattr(exc.value, "code", None) is ErrorCode.RATE_LIMITED
            assert getattr(exc.value, "retry_after", None) == 4
        finally:
            await runtime.close()
            await server.close()

    asyncio.run(scenario())


def test_http_runtime_enforces_total_timeout():
    async def scenario():
        async def slow(_request):
            await asyncio.sleep(0.1)
            return web.Response(text="late")

        app = web.Application()
        app.router.add_get("/", slow)
        server = TestServer(app)
        await server.start_server()
        runtime = HttpRuntime(total_timeout=0.01)
        try:
            with pytest.raises(HttpError) as exc:
                await runtime.request("GET", str(server.make_url("/")))
            assert exc.value.code is ErrorCode.NETWORK_ERROR
        finally:
            await runtime.close()
            await server.close()

    asyncio.run(scenario())


def test_http_runtime_cancellation_stops_request():
    async def scenario():
        async def slow(_request):
            await asyncio.sleep(1)
            return web.Response(text="late")

        app = web.Application()
        app.router.add_get("/", slow)
        server = TestServer(app)
        await server.start_server()
        runtime = HttpRuntime()
        cancel = asyncio.Event()
        task = asyncio.create_task(runtime.request("GET", str(server.make_url("/")), cancel=cancel))
        await asyncio.sleep(0.02)
        cancel.set()
        try:
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            await runtime.close()
            await server.close()

    asyncio.run(scenario())


def test_http_runtime_cancellation_interrupts_origin_retry_wait():
    async def scenario():
        async def limited(_request):
            return web.Response(status=429, headers={"Retry-After": "30"})

        app = web.Application()
        app.router.add_get("/", limited)
        server = TestServer(app)
        await server.start_server()
        runtime = HttpRuntime(max_retry_wait=60)
        url = str(server.make_url("/"))
        cancel = asyncio.Event()
        try:
            with pytest.raises(HttpError) as exc:
                await runtime.request("GET", url)
            assert exc.value.code is ErrorCode.RATE_LIMITED
            task = asyncio.create_task(runtime.request("GET", url, cancel=cancel))
            await asyncio.sleep(0.01)
            cancel.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.2)
        finally:
            await runtime.close()
            await server.close()

    asyncio.run(scenario())


def test_http_runtime_rejects_unsafe_redirect():
    async def scenario():
        async def redirect(_request):
            raise web.HTTPFound("file:///etc/passwd")

        app = web.Application()
        app.router.add_get("/", redirect)
        server = TestServer(app)
        await server.start_server()
        runtime = HttpRuntime()
        try:
            with pytest.raises(Exception):
                await runtime.request("GET", str(server.make_url("/")))
        finally:
            await runtime.close()
            await server.close()

    asyncio.run(scenario())


def test_http_runtime_rejects_redirect_with_password_only_userinfo():
    async def scenario():
        async def redirect(request):
            target = str(request.url.with_path("/target"))
            target = target.replace("http://", "http://:secret@", 1)
            raise web.HTTPFound(target)

        app = web.Application()
        app.router.add_get("/", redirect)
        server = TestServer(app)
        await server.start_server()
        runtime = HttpRuntime()
        try:
            with pytest.raises(HttpError) as exc:
                await runtime.request("GET", str(server.make_url("/")))
            assert exc.value.code is ErrorCode.INVALID_REQUEST
        finally:
            await runtime.close()
            await server.close()

    asyncio.run(scenario())


def test_http_runtime_normalizes_invalid_redirect_port():
    async def scenario():
        async def redirect(_request):
            return web.Response(
                status=302, headers={"Location": "https://example.test:bad/target"}
            )

        app = web.Application()
        app.router.add_get("/", redirect)
        server = TestServer(app)
        await server.start_server()
        runtime = HttpRuntime()
        try:
            with pytest.raises(HttpError) as exc:
                await runtime.request("GET", str(server.make_url("/")))
            assert exc.value.code is ErrorCode.INVALID_REQUEST
        finally:
            await runtime.close()
            await server.close()

    asyncio.run(scenario())


def test_http_runtime_rejects_error_status_instead_of_returning_body():
    async def scenario():
        async def failed(_request):
            return web.Response(status=503, text="error body")

        app = web.Application()
        app.router.add_get("/", failed)
        server = TestServer(app)
        await server.start_server()
        runtime = HttpRuntime()
        try:
            with pytest.raises(Exception) as exc:
                await runtime.request("GET", str(server.make_url("/")))
            assert getattr(exc.value, "code", None) is ErrorCode.NETWORK_ERROR
        finally:
            await runtime.close()
            await server.close()

    asyncio.run(scenario())


def test_cross_origin_redirect_does_not_forward_credentials():
    async def scenario():
        seen = []

        async def destination(request):
            seen.append(request.headers.get("Authorization"))
            return web.Response(text="ok")

        destination_app = web.Application()
        destination_app.router.add_get("/target", destination)
        destination_server = TestServer(destination_app)
        await destination_server.start_server()

        async def redirect(_request):
            raise web.HTTPFound(str(destination_server.make_url("/target")))

        source_app = web.Application()
        source_app.router.add_get("/", redirect)
        source_server = TestServer(source_app)
        await source_server.start_server()
        runtime = HttpRuntime()
        try:
            response = await runtime.request(
                "GET", str(source_server.make_url("/")), headers={"Authorization": "secret"}
            )
            assert await response.text() == "ok"
            assert seen == [None]
        finally:
            await runtime.close()
            await source_server.close()
            await destination_server.close()

    asyncio.run(scenario())


def test_runtime_defaults_send_configured_headers_and_strip_cookie_on_redirect():
    async def scenario():
        seen = []

        async def destination(request):
            seen.append((request.headers.get("Cookie"), request.headers.get("User-Agent")))
            return web.Response(text="ok")

        destination_app = web.Application()
        destination_app.router.add_get("/target", destination)
        destination_server = TestServer(destination_app)
        await destination_server.start_server()

        async def redirect(request):
            seen.append((request.headers.get("Cookie"), request.headers.get("User-Agent")))
            raise web.HTTPFound(str(destination_server.make_url("/target")))

        source_app = web.Application()
        source_app.router.add_get("/", redirect)
        source_server = TestServer(source_app)
        await source_server.start_server()
        runtime = HttpRuntime(cookie="session=private", user_agent="dler-kun-test")
        try:
            response = await runtime.request("GET", str(source_server.make_url("/")))
            assert await response.text() == "ok"
            assert seen == [("session=private", "dler-kun-test"), (None, "dler-kun-test")]
        finally:
            await runtime.close()
            await source_server.close()
            await destination_server.close()

    asyncio.run(scenario())


def test_runtime_configures_socks_proxy_connector():
    async def scenario():
        runtime = HttpRuntime(proxy="socks5://127.0.0.1:1080", local_addr="127.0.0.1")
        try:
            await runtime._get_session()
            from aiohttp_socks import ProxyConnector

            assert isinstance(runtime._connector, ProxyConnector)
        finally:
            await runtime.close()

    asyncio.run(scenario())


def test_http_runtime_awaits_request_cleanup_after_cancel_event():
    async def scenario():
        from typing import cast

        import aiohttp

        started = asyncio.Event()
        cleanup_started = asyncio.Event()
        finish_cleanup = asyncio.Event()
        cleaned = asyncio.Event()

        class Session:
            closed = False

            async def request(self, *_args, **_kwargs):
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cleanup_started.set()
                    await finish_cleanup.wait()
                    raise
                finally:
                    cleaned.set()

        runtime = HttpRuntime()
        async def session() -> aiohttp.ClientSession:
            return cast(aiohttp.ClientSession, Session())

        runtime._get_session = session
        cancel = asyncio.Event()
        task = asyncio.create_task(runtime.request("GET", "https://example.test/", cancel=cancel))
        await started.wait()
        cancel.set()
        await cleanup_started.wait()
        assert not task.done()
        finish_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()

    asyncio.run(scenario())
