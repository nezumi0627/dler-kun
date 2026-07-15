from __future__ import annotations

import json
import mimetypes
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .app import DlerKunApp, to_jsonable


STATIC_DIR = Path(__file__).resolve().parent / "static"


def run_web_server(
    app: DlerKunApp,
    host: str = "127.0.0.1",
    port: int = 8787,
    open_browser: bool = True,
) -> None:
    handler = build_handler(app)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}"
    print(f"dler-kun web UI: {url}")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    server.serve_forever()


def build_handler(app: DlerKunApp):
    class DlerKunHandler(BaseHTTPRequestHandler):
        server_version = "dler-kun/0.1"

        def do_GET(self) -> None:  # noqa: N802 - stdlib hook name.
            parsed = urlparse(self.path)
            if parsed.path == "/api/snapshot":
                self.send_json(app.snapshot())
                return
            if parsed.path == "/api/detect":
                query = parse_qs(parsed.query)
                self.send_json(app.detect(query.get("url", [""])[0]))
                return
            self.serve_static(parsed.path)

        def do_POST(self) -> None:  # noqa: N802 - stdlib hook name.
            try:
                payload = self.read_json()
            except ValueError as exc:
                self.send_json({"error": str(exc)}, status=400)
                return
            if self.path == "/api/download":
                urls = payload.get("urls") or []
                if isinstance(urls, str):
                    urls = [line.strip() for line in urls.splitlines() if line.strip()]
                try:
                    self.send_json(
                        app.download_urls(
                            urls,
                            output_dir=payload.get("output_dir") or None,
                            options=payload.get("options") or {},
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - keep web server alive.
                    self.send_json({"error": str(exc)}, status=500)
                return
            if self.path == "/api/download/start":
                urls = payload.get("urls") or []
                if isinstance(urls, str):
                    urls = [line.strip() for line in urls.splitlines() if line.strip()]
                self.send_json(
                    app.start_download_urls(
                        urls,
                        output_dir=payload.get("output_dir") or None,
                        options=payload.get("options") or {},
                    ),
                    status=202,
                )
                return
            if self.path == "/api/crawl":
                try:
                    self.send_json(
                        app.crawl(
                            payload.get("service", "85xo"),
                            output_dir=payload.get("output_dir") or None,
                            seeds=payload.get("seeds") or [],
                            days=int(payload.get("days", 10)),
                            download=bool(payload.get("download", False)),
                            options=payload.get("options") or {},
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - keep web server alive.
                    self.send_json({"error": str(exc)}, status=500)
                return
            if self.path == "/api/crawl/start":
                self.send_json(
                    app.start_crawl(
                        payload.get("service", "85xo"),
                        output_dir=payload.get("output_dir") or None,
                        seeds=payload.get("seeds") or [],
                        days=int(payload.get("days", 10)),
                        download=bool(payload.get("download", False)),
                        options=payload.get("options") or {},
                    ),
                    status=202,
                )
                return
            self.send_error(404)

        def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib hook name.
            self.send_response(204)
            self.send_cors_headers()
            self.end_headers()

        def serve_static(self, path: str) -> None:
            relative = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (STATIC_DIR / relative).resolve()
            if STATIC_DIR not in target.parents and target != STATIC_DIR:
                self.send_error(403)
                return
            if not target.exists() or not target.is_file():
                self.send_error(404)
                return
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(data)

        def read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError("invalid JSON payload") from exc
            if not isinstance(payload, dict):
                raise ValueError("JSON payload must be an object")
            return payload

        def send_json(self, payload, status: int = 200) -> None:
            data = json.dumps(to_jsonable(payload), ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(data)

        def send_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def log_message(self, format: str, *args) -> None:
            print(f"[web] {format % args}")

    return DlerKunHandler
