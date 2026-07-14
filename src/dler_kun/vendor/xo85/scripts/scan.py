from __future__ import annotations

import argparse

from common import add_crawl_arguments, collect_seeds

from xo_dler import CrawlConfig, crawl_once  # type: ignore[reportMissingImports]


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan pages and print downloadable media URLs.")
    add_crawl_arguments(parser)
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

    print(f"found: {len(items)}")
    for item in items:
        published = item.published_at.isoformat() if item.published_at else "unknown-date"
        print(f"{published}\t{item.url}")


if __name__ == "__main__":
    main()
