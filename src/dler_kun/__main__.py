from __future__ import annotations

import argparse
import json
from pathlib import Path

from .app import DlerKunApp, to_jsonable
from .web import run_web_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="dler-kun unified downloader")
    sub = parser.add_subparsers(dest="command")

    detect = sub.add_parser("detect", help="Detect service for URL")
    detect.add_argument("url")

    download = sub.add_parser("download", help="Download one or more URLs")
    download.add_argument("urls", nargs="+")
    download.add_argument("-o", "--output-dir", type=Path)
    download.add_argument("--force", action="store_true")
    download.add_argument("--verbose", action="store_true")
    download.add_argument("--parallel", type=int)
    download.add_argument("--seg-workers", type=int)
    download.add_argument("--quality")
    download.add_argument("--password")

    crawl = sub.add_parser("crawl", help="Run an existing engine crawler")
    crawl.add_argument("service", choices=["85xo", "gofile", "dl"])
    crawl.add_argument("--seed", action="append", default=[])
    crawl.add_argument("--days", type=int, default=10)
    crawl.add_argument("-o", "--output-dir", type=Path)
    crawl.add_argument("--download", action="store_true")
    crawl.add_argument("--max-pages", type=int)
    crawl.add_argument("--max-depth", type=int)
    crawl.add_argument("--delay-seconds", type=float)
    crawl.add_argument("--network-capture-seconds", type=float)
    crawl.add_argument("--browser-path")
    crawl.add_argument("--include-undated", action="store_true")
    crawl.add_argument("--overwrite", action="store_true")
    crawl.add_argument("--method", choices=["fast", "legacy"], default="fast")
    crawl.add_argument("--resolve-workers", type=int, default=6)
    crawl.add_argument("--parallel-downloads", type=int, default=4)
    crawl.add_argument("--download-read-timeout", type=float, default=30.0)
    crawl.add_argument("--download-attempts", type=int, default=2)

    web = sub.add_parser("web", help="Run local Web UI")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8787)

    config = sub.add_parser("config", help="Print effective config")
    config.add_argument("--save", action="store_true", help="Write default config.json")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    app = DlerKunApp()

    if args.command == "detect":
        print_json(app.detect(args.url))
        return

    if args.command == "download":
        options = {
            key: value
            for key, value in vars(args).items()
            if key
            in {
                "force",
                "verbose",
                "parallel",
                "seg_workers",
                "quality",
                "password",
            }
            and value not in (None, False, "")
        }
        print_json(app.download_urls(args.urls, args.output_dir, options))
        return

    if args.command == "crawl":
        options = {
            key: value
            for key, value in vars(args).items()
            if key
            in {
                "max_pages",
                "max_depth",
                "delay_seconds",
                "network_capture_seconds",
                "browser_path",
                "include_undated",
                "overwrite",
                "method",
                "resolve_workers",
                "parallel_downloads",
                "download_read_timeout",
                "download_attempts",
            }
            and value not in (None, False, "")
        }
        print_json(
            app.crawl(
                args.service,
                output_dir=args.output_dir,
                seeds=args.seed,
                days=args.days,
                download=args.download,
                options=options,
            )
        )
        return

    if args.command == "web":
        run_web_server(app, args.host, args.port)
        return

    if args.command == "config":
        if args.save:
            app.config.save()
        print_json(app.config.as_dict())
        return

    parser.print_help()


def print_json(value) -> None:
    print(json.dumps(to_jsonable(value), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
