from __future__ import annotations

import argparse
from pathlib import Path

from common import add_crawl_arguments, collect_seeds

from xo_dler import CrawlConfig, DownloadConfig, crawl_once, download_items  # type: ignore[reportMissingImports]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download media discovered by the crawler."
    )
    add_crawl_arguments(parser)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("downloads"), help="Download directory."
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="Download again even if a file exists."
    )
    args = parser.parse_args()

    items = crawl_once(
        CrawlConfig(
            seeds=collect_seeds(args),
            days=args.days,
            max_pages=args.max_pages,
            max_depth=args.max_depth,
            delay_seconds=args.delay_seconds,
            include_undated=args.include_undated,
            network_capture_seconds=args.network_capture_seconds,
            browser_path=args.browser_path,
        )
    )
    print(f"download targets: {len(items)}")

    paths = download_items(
        items,
        DownloadConfig(
            output_dir=args.output_dir,
            skip_existing=not args.overwrite,
        ),
    )
    print(f"saved: {len(paths)}")


if __name__ == "__main__":
    main()
