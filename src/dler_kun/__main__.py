from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .app import DlerKunApp
from .cli import (
    exit_with,
    print_cancel_result,
    print_config,
    print_detect,
    print_download_results,
    print_job_result,
    print_sites,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dler-kun",
        description="Unified downloader for twimg / gofile / 85xo / mvfile / gofilerun",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full machine-readable JSON instead of a short summary",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--local-addr",
        help="Bind source IP for downloads (e.g. iPhone USB tethering 172.20.10.2)",
    )
    common.add_argument("--proxy", help="HTTP/SOCKS proxy override")
    common.add_argument("--user-agent", dest="user_agent", help="User-Agent override")
    common.add_argument("--cookie", help="Cookie header override")

    engine_opts = argparse.ArgumentParser(add_help=False)
    engine_opts.add_argument("--api-base", help="mvfile/gofilerun: API base URL override")
    engine_opts.add_argument("--timeout", dest="timeout_seconds", type=float, help="Network timeout seconds")

    detect = sub.add_parser("detect", help="Detect which engine handles a URL")
    detect.add_argument("url")

    sub.add_parser("sites", help="List supported sites / engines")

    sub.add_parser("help", help="Show this help")

    download = sub.add_parser(
        "download", help="Download one or more URLs", parents=[common, engine_opts]
    )
    download.add_argument("urls", nargs="+")
    download.add_argument("-o", "--output-dir", type=Path)
    download.add_argument("--force", action="store_true")
    download.add_argument(
        "--metadata", action="store_true", help="Write <file>.json metadata sidecar (default: off)"
    )
    download.add_argument("--verbose", action="store_true")
    download.add_argument("--parallel", type=int)
    download.add_argument("--seg-workers", type=int)
    download.add_argument(
        "--segment-concurrency",
        type=int,
        help="mixixxx: concurrent HLS segment fetches (default 4)",
    )
    download.add_argument("--quality")
    download.add_argument("--password")
    download.add_argument(
        "--single",
        action="store_true",
        help="mvfile: download only the requested file (default: whole channel list)",
    )
    download.add_argument(
        "--hls-workers",
        type=int,
        default=None,
        help="mvfile: concurrent HLS segment fetches (default 8)",
    )
    download.add_argument(
        "--parallel-urls",
        type=int,
        default=None,
        help="Download multiple URLs concurrently (default: auto, up to 4; 1 = sequential)",
    )
    download.add_argument(
        "--god",
        action="store_true",
        help="Maximize performance: parallel URLs, HLS workers, and segment concurrency",
    )

    crawl = sub.add_parser(
        "crawl", help="Crawl an engine and optionally download", parents=[common, engine_opts]
    )
    crawl.add_argument(
        "service", choices=["85xo", "gofile", "mvfile", "gofilerun", "mixixxx"]
    )
    crawl.add_argument(
        "--seed", action="append", default=[], help="Override crawl seed URL"
    )
    crawl.add_argument("--days", type=int, help="Lookback window in days (85xo)")
    crawl.add_argument("-o", "--output-dir", type=Path)
    crawl.add_argument(
        "--download", action="store_true", help="Download discovered media"
    )
    crawl.add_argument("--max-pages", type=int)
    crawl.add_argument("--max-depth", type=int)
    crawl.add_argument("--delay-seconds", type=float)
    crawl.add_argument("--network-capture-seconds", type=float)
    crawl.add_argument("--browser-path")
    crawl.add_argument("--include-undated", action="store_true")
    crawl.add_argument("--overwrite", action="store_true")
    crawl.add_argument(
        "--metadata", action="store_true", help="Write <file>.json metadata sidecar (default: off)"
    )
    crawl.add_argument("--method", choices=["fast", "legacy"], default="fast")
    crawl.add_argument("--resolve-workers", type=int)
    crawl.add_argument(
        "--discover-workers",
        type=int,
        help="Concurrent listing-page fetches during discovery (85xo fast method)",
    )
    crawl.add_argument("--parallel-downloads", type=int)
    crawl.add_argument(
        "--segment-concurrency",
        type=int,
        help="mixixxx: concurrent HLS segment fetches per browser session (default 4)",
    )
    crawl.add_argument(
        "--hls-workers",
        type=int,
        default=None,
        help="mvfile: concurrent HLS segment fetches (default 8)",
    )
    crawl.add_argument(
        "--download-read-timeout",
        type=float,
        help="Abort only when transfer stalls below 1 KiB/s for this many seconds",
    )
    crawl.add_argument("--download-attempts", type=int)
    crawl.add_argument(
        "--download-max-time",
        type=float,
        help="Optional hard cap for a single curl transfer (seconds)",
    )
    crawl.add_argument(
        "--source",
        action="append",
        default=[],
        help="Source alias (gofile: douga/lab; 85xo: top-rated/most-popular/tags/home/members/...)",
    )
    crawl.add_argument("--limit", type=int)
    crawl.add_argument("--max-more-clicks", type=int)

    ranking = sub.add_parser(
        "ranking", help="Run a ranking crawler (gofile)", parents=[common]
    )
    ranking.add_argument("service", choices=["gofile"])
    ranking.add_argument("--seed", action="append", default=[])
    ranking.add_argument("--source", action="append", default=[])
    ranking.add_argument("--limit", type=int)
    ranking.add_argument("--max-more-clicks", type=int)
    ranking.add_argument("-o", "--output-dir", type=Path)
    ranking.add_argument("--download", action="store_true")

    cancel = sub.add_parser("cancel", help="Cancel running job(s)")
    cancel.add_argument("job_id", nargs="?")
    cancel.add_argument("--all", action="store_true")

    config = sub.add_parser("config", help="Show effective config (JSON)")
    config.add_argument("--save", action="store_true", help="Write default config.json")

    return parser


def _options_from_args(args: argparse.Namespace, keys: set[str]) -> dict:
    return {
        key: value
        for key, value in vars(args).items()
        if key in keys and value not in (None, False, "")
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = bool(args.json)
    # JSON mode must keep stdout clean; disable live progress bars.
    app = DlerKunApp(live_progress=False if as_json else None)

    try:
        return _dispatch(app, args, as_json, parser)
    except KeyboardInterrupt:
        app.stop_event.set()
        app.cancel_all()
        app.progress.close_live()
        print("[WARNING] Interrupted (Ctrl+C). Job(s) cancelled.", file=sys.stderr)
        return 130


def _dispatch(
    app: DlerKunApp, args: argparse.Namespace, as_json: bool, parser: argparse.ArgumentParser
) -> int:
    if args.command == "detect":
        return print_detect(app.detect(args.url), as_json=as_json)

    if args.command == "sites":
        return print_sites(app.sites(), as_json=as_json)

    if args.command == "help":
        parser.print_help()
        return 0

    if args.command == "download":
        options = _options_from_args(
            args,
            {"force", "verbose", "parallel", "seg_workers", "segment_concurrency", "quality", "password", "metadata", "hls_workers", "parallel_urls", "local_addr", "proxy", "user_agent", "cookie", "api_base", "timeout_seconds", "god"},
        )
        if getattr(args, "god", False):
            options["god"] = True
        if getattr(args, "single", False):
            options["related"] = False
        return print_download_results(
            app.download_urls(args.urls, args.output_dir, options),
            as_json=as_json,
        )

    if args.command == "crawl":
        options = _options_from_args(
            args,
            {
                "max_pages",
                "max_depth",
                "delay_seconds",
                "network_capture_seconds",
                "browser_path",
                "include_undated",
                "overwrite",
                "metadata",
                "method",
                "resolve_workers",
                "discover_workers",
                "parallel_downloads",
                "segment_concurrency",
                "hls_workers",
                "download_read_timeout",
                "download_attempts",
                "download_max_time",
                "limit",
                "max_more_clicks",
                "local_addr",
                "proxy",
                "user_agent",
                "cookie",
                "api_base",
                "timeout_seconds",
            },
        )
        if args.source:
            options["sources"] = list(args.source)
        return print_job_result(
            app.crawl(
                args.service,
                output_dir=args.output_dir,
                seeds=args.seed,
                days=args.days,
                download=args.download,
                options=options,
            ),
            as_json=as_json,
        )

    if args.command == "ranking":
        options = _options_from_args(
            args, {"limit", "max_more_clicks", "local_addr", "proxy", "user_agent", "cookie"}
        )
        if args.source:
            options["sources"] = list(args.source)
        return print_job_result(
            app.ranking(
                args.service,
                output_dir=args.output_dir,
                seeds=args.seed,
                download=args.download,
                options=options,
            ),
            as_json=as_json,
        )

    if args.command == "config":
        if args.save:
            app.config.save()
        return print_config(app.config.as_dict(), as_json=True)

    if args.command == "cancel":
        if args.all:
            return print_cancel_result(app.cancel_all(), as_json=as_json)
        if args.job_id:
            return print_cancel_result(app.cancel_job(args.job_id), as_json=as_json)
        parser.error("cancel requires JOB_ID or --all")

    parser.print_help()
    return 2


if __name__ == "__main__":
    exit_with(main())
