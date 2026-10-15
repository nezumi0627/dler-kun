"""First-party CLI entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from dler_kun2.domain.errors import EngineError
from dler_kun2.infrastructure.state.config import ConfigStore
from dler_kun2.presentation.cli.commands import run_command
from dler_kun2.presentation.cli.output import emit
from dler_kun2.routing.defaults import build_registry
from dler_kun2.routing.registry import EngineRegistry, RouteError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dler-kun2")
    parser.add_argument("--json", action="store_true", dest="global_json")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("detect", "sites", "download", "crawl", "ranking", "jobs", "cancel", "config"):
        command = commands.add_parser(name)
        if name == "detect":
            command.add_argument("target")
        if name == "download":
            command.add_argument("target", nargs="+")
        if name == "cancel":
            command.add_argument("target", nargs="?")
            command.add_argument("--all", action="store_true")
        if name in {"crawl", "ranking"}:
            command.add_argument("service")
            command.add_argument("--seed", action="append", default=[])
            command.add_argument("--source", action="append", default=[])
        if name == "crawl":
            command.add_argument("--days", type=int)
        if name in {"download", "crawl"}:
            command.add_argument("--max-pages", type=int)
            command.add_argument("--password")
        if name == "download":
            command.add_argument("--force", action="store_true")
        if name == "crawl":
            command.add_argument("--overwrite", action="store_true")
        if name in {"crawl", "ranking"}:
            command.add_argument("--limit", type=int)
        if name == "crawl":
            command.add_argument("--resolve-workers", type=int)
        if name in {"download", "crawl"}:
            command.add_argument("--segment-concurrency", type=int)
            command.add_argument("--browser-path")
            command.add_argument("--ffmpeg-path")
            command.add_argument("--timeout-seconds", type=float)
        if name == "config":
            command.add_argument("--save", action="store_true", help="Write the effective config.json")
        command.add_argument("--json", action="store_true")
        if name in {"download", "crawl", "ranking"}:
            command.add_argument("-o", "--output-dir", type=Path)
        if name == "download":
            command.add_argument("--parallel-urls", type=int, default=4, help="Maximum URLs downloaded concurrently")
        if name in {"crawl", "ranking"}:
            command.add_argument("--download", action="store_true")
    args = parser.parse_args(argv)
    json_mode = args.global_json or args.json
    target = getattr(args, "service", getattr(args, "target", None))
    targets = tuple(target) if args.command == "download" else None
    if args.command == "download" and target:
        target = target[0]
    seeds = tuple(getattr(args, "seed", ())) + tuple(getattr(args, "source", ()))
    option_names = ("max_pages", "limit", "password", "segment_concurrency", "browser_path", "ffmpeg_path", "timeout_seconds", "resolve_workers", "force", "overwrite")
    options = {name: value for name in option_names if (value := getattr(args, name, None)) not in (None, False)}
    try:
        configured_output = ConfigStore().as_dict(redact=False).get("output_dir", "downloads")
        output_dir = getattr(args, "output_dir", None) or Path(str(configured_output))
        value = run_command(args.command, target, build_registry(EngineRegistry()), output_dir=output_dir, download_items=getattr(args, "download", False), seeds=seeds, days=getattr(args, "days", None), save_config=getattr(args, "save", False), cancel_all=getattr(args, "all", False), targets=targets, parallel_urls=getattr(args, "parallel_urls", 4), options=options)
    except RouteError as exc:
        value = exc.error
    except EngineError as exc:
        value = exc
    emit(value, json_mode=json_mode)
    return 2 if isinstance(value, EngineError) else 0


if __name__ == "__main__":
    raise SystemExit(main())
