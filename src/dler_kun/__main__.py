from __future__ import annotations

import argparse
from pathlib import Path

from .app import DlerKunApp
from .cli import (
    exit_with,
    print_cancel_result,
    print_config,
    print_detect,
    print_download_results,
    print_job_result,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dler-kun",
        description="Unified downloader for twimg / gofile / 85xo",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full machine-readable JSON instead of a short summary",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    detect = sub.add_parser("detect", help="Detect which engine handles a URL")
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

    crawl = sub.add_parser("crawl", help="Crawl an engine and optionally download")
    crawl.add_argument("service", choices=["85xo", "gofile"])
    crawl.add_argument("--seed", action="append", default=[], help="Override crawl seed URL")
    crawl.add_argument("--days", type=int, help="Lookback window in days (85xo)")
    crawl.add_argument("-o", "--output-dir", type=Path)
    crawl.add_argument("--download", action="store_true", help="Download discovered media")
    crawl.add_argument("--max-pages", type=int)
    crawl.add_argument("--max-depth", type=int)
    crawl.add_argument("--delay-seconds", type=float)
    crawl.add_argument("--network-capture-seconds", type=float)
    crawl.add_argument("--browser-path")
    crawl.add_argument("--include-undated", action="store_true")
    crawl.add_argument("--overwrite", action="store_true")
    crawl.add_argument("--method", choices=["fast", "legacy"], default="fast")
    crawl.add_argument("--resolve-workers", type=int)
    crawl.add_argument("--parallel-downloads", type=int)
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
        help="Ranking source alias (gofile: douga/lab)",
    )
    crawl.add_argument("--limit", type=int)
    crawl.add_argument("--max-more-clicks", type=int)

    ranking = sub.add_parser("ranking", help="Run a ranking crawler (gofile)")
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

    if args.command == "detect":
        return print_detect(app.detect(args.url), as_json=as_json)

    if args.command == "download":
        options = _options_from_args(
            args,
            {"force", "verbose", "parallel", "seg_workers", "quality", "password"},
        )
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
                "method",
                "resolve_workers",
                "parallel_downloads",
                "download_read_timeout",
                "download_attempts",
                "download_max_time",
                "limit",
                "max_more_clicks",
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
        options = _options_from_args(args, {"limit", "max_more_clicks"})
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
