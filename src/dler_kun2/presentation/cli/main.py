"""First-party CLI entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from dler_kun2.domain.errors import EngineError
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
        if name in {"detect", "download", "cancel"}:
            command.add_argument("target")
        if name in {"crawl", "ranking"}:
            command.add_argument("service")
            command.add_argument("--seed", action="append", default=[])
        if name == "crawl":
            command.add_argument("--days", type=int)
        if name == "config":
            command.add_argument("--save", action="store_true", help="Write the effective config.json")
        command.add_argument("--json", action="store_true")
        if name in {"download", "crawl", "ranking"}:
            command.add_argument("-o", "--output-dir", type=Path, default=Path("downloads"))
        if name in {"crawl", "ranking"}:
            command.add_argument("--download", action="store_true")
    args = parser.parse_args(argv)
    json_mode = args.global_json or args.json
    try:
        value = run_command(args.command, getattr(args, "service", getattr(args, "target", None)), build_registry(EngineRegistry()), output_dir=getattr(args, "output_dir", Path("downloads")), download_items=getattr(args, "download", False), seeds=tuple(getattr(args, "seed", ())), days=getattr(args, "days", None), save_config=getattr(args, "save", False))
    except RouteError as exc:
        value = exc.error
    except EngineError as exc:
        value = exc
    emit(value, json_mode=json_mode)
    return 2 if isinstance(value, EngineError) else 0


if __name__ == "__main__":
    raise SystemExit(main())
