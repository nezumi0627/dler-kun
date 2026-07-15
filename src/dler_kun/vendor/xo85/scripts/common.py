from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = PROJECT_ROOT / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))


def add_crawl_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--seed",
        action="append",
        default=[],
        help="Crawl start URL. Can be specified more than once.",
    )
    parser.add_argument(
        "--seed-file",
        type=Path,
        help="Text file containing one crawl start URL per line.",
    )
    parser.add_argument(
        "--days", type=int, default=10, help="Keep items from this many days back."
    )
    parser.add_argument(
        "--max-pages", type=int, default=50, help="Maximum pages to fetch per run."
    )
    parser.add_argument(
        "--max-depth", type=int, default=2, help="Maximum link depth from seeds."
    )
    parser.add_argument(
        "--delay-seconds", type=float, default=1.0, help="Delay between page fetches."
    )
    parser.add_argument(
        "--network-capture-seconds",
        type=float,
        default=15.0,
        help="Seconds to watch browser network traffic on each video page.",
    )
    parser.add_argument(
        "--browser-path",
        help="Chrome or Edge executable path for browser network capture.",
    )
    parser.add_argument(
        "--include-undated",
        action="store_true",
        help="Include media links when no date can be parsed near the link.",
    )


def collect_seeds(args: argparse.Namespace) -> list[str]:
    seeds = list(args.seed)
    if args.seed_file:
        seeds.extend(
            line.strip()
            for line in args.seed_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )

    if not seeds:
        raise SystemExit("At least one --seed or --seed-file is required.")

    return seeds
