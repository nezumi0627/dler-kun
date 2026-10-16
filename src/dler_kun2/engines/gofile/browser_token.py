"""Generate fresh GoFile website tokens inside an isolated official-site browser."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from dler_kun2.domain.errors import EngineError, ErrorCode


class BrowserWebsiteTokenProvider:
    """Delegate WT generation to the current first-party page script."""

    def __init__(self, browser_path: str | None = None):
        self.browser_path = browser_path or _find_browser()

    async def generate(self, account_token: str) -> tuple[str, str, str]:
        if not self.browser_path:
            raise EngineError(ErrorCode.DEPENDENCY_MISSING, "Chrome or Edge is required for current GoFile signing")
        try:
            return await asyncio.to_thread(self._generate, account_token)
        except FileNotFoundError as exc:
            raise EngineError(ErrorCode.DEPENDENCY_MISSING, "configured GoFile browser was not found") from exc
        except EngineError:
            raise
        except Exception as exc:
            raise EngineError(ErrorCode.NETWORK_ERROR, "GoFile website token generation failed") from exc

    def _generate(self, account_token: str) -> tuple[str, str, str]:
        browser_path = self.browser_path
        if not browser_path:
            raise EngineError(ErrorCode.DEPENDENCY_MISSING, "Chrome or Edge is required for current GoFile signing")
        try:
            from websockets.sync.client import connect
        except ImportError as exc:
            raise EngineError(ErrorCode.DEPENDENCY_MISSING, "websockets is required for current GoFile signing") from exc

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        with tempfile.TemporaryDirectory(prefix="dler-kun2-gofile-wt-") as temporary:
            process = subprocess.Popen(
                [browser_path, "--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions", "--remote-allow-origins=*", f"--remote-debugging-port={port}", f"--user-data-dir={Path(temporary) / 'profile'}", "https://gofile.io/"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            websocket = None
            try:
                target = _wait_for_page(port, process, 30)
                websocket = connect(target, open_timeout=10, close_timeout=2, max_size=2 * 1024 * 1024)
                sequence = 0

                def call(method: str, params: dict | None = None, timeout: float = 20) -> dict:
                    nonlocal sequence
                    sequence += 1
                    command_id = sequence
                    websocket.send(json.dumps({"id": command_id, "method": method, "params": params or {}}, separators=(",", ":")))
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        event = json.loads(websocket.recv(timeout=min(0.5, deadline - time.monotonic())))
                        if event.get("id") != command_id:
                            continue
                        if "error" in event:
                            raise EngineError(ErrorCode.NETWORK_ERROR, "GoFile page rejected token evaluation")
                        return event.get("result", {})
                    raise EngineError(ErrorCode.NETWORK_ERROR, "GoFile page token evaluation timed out")

                call("Runtime.enable")
                expression = "typeof globalThis.generateWT === 'function'"
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    result = call("Runtime.evaluate", {"expression": expression, "returnByValue": True}, timeout=2)
                    if result.get("result", {}).get("value") is True:
                        break
                    time.sleep(0.25)
                else:
                    raise EngineError(ErrorCode.DEPENDENCY_MISSING, "current GoFile token script did not load")

                token_json = json.dumps(account_token)
                expression = f"globalThis.generateWT({token_json}).then(wt => JSON.stringify({{wt, ua: navigator.userAgent, language: navigator.language}}))"
                result = call("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True})
                remote = result.get("result", {}).get("value")
                if not isinstance(remote, str):
                    raise EngineError(ErrorCode.NETWORK_ERROR, "current GoFile script returned no website token")
                parsed = json.loads(remote)
                wt, user_agent, language = parsed.get("wt"), parsed.get("ua"), parsed.get("language")
                if not all(isinstance(value, str) and value for value in (wt, user_agent, language)):
                    raise EngineError(ErrorCode.NETWORK_ERROR, "current GoFile script returned invalid signing data")
                return wt, user_agent, language
            finally:
                if websocket is not None:
                    websocket.close()
                _stop(process)


def _wait_for_page(port: int, process: subprocess.Popen, timeout: float) -> str:
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise EngineError(ErrorCode.DEPENDENCY_MISSING, "GoFile browser exited before startup")
        try:
            request = Request(f"http://127.0.0.1:{port}/json/list")
            with opener.open(request, timeout=1) as response:
                pages = json.loads(response.read())
            for page in pages:
                target = page.get("webSocketDebuggerUrl") if isinstance(page, dict) else None
                if isinstance(target, str) and target.startswith(f"ws://127.0.0.1:{port}/"):
                    return target
        except (OSError, ValueError):
            time.sleep(0.2)
    raise EngineError(ErrorCode.NETWORK_ERROR, "GoFile browser page did not become ready")


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _find_browser() -> str | None:
    configured = os.environ.get("GOFILE_BROWSER_PATH")
    if configured:
        return configured if Path(configured).is_file() else None
    for name in ("chrome", "msedge", "google-chrome", "chromium"):
        if path := shutil.which(name):
            return path
    if os.name == "nt":
        for path in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
            if Path(path).is_file():
                return path
    return None
