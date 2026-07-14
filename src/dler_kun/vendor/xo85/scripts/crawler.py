from __future__ import annotations

import argparse
from pathlib import Path
from time import sleep

from common import add_crawl_arguments, collect_seeds

from xo_dler import CrawlConfig, DownloadConfig, crawl_once, download_items  # type: ignore[reportMissingImports]


def main() -> None:
    parser = argparse.ArgumentParser(description="Continuously crawl and download media at an interval.")
    add_crawl_arguments(parser)
    parser.add_argument("--output-dir", type=Path, default=Path("downloads"), help="Download directory.")
    parser.add_argument("--interval-minutes", type=float, default=60.0, help="Minutes between crawl runs.")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    args = parser.parse_args()

    seeds = collect_seeds(args)
    cycle = 1

    while True:
        print(f"[cycle {cycle}] crawl start")
        items = crawl_once(
            CrawlConfig(
                seeds=seeds,
                days=args.days,
                max_pages=args.max_pages,
                max_depth=args.max_depth,
                delay_seconds=args.delay_seconds,
                include_undated=args.include_undated,
                network_capture_seconds=args.network_capture_seconds,
                browser_path=args.browser_path,
            )
        )
        print(f"[cycle {cycle}] download targets: {len(items)}")
        download_items(
            items,
            DownloadConfig(
                output_dir=args.output_dir,
                skip_existing=True,
            ),
        )

        if args.once:
            break

        cycle += 1
        sleep(max(args.interval_minutes, 0.1) * 60)


if __name__ == "__main__":
    main()
