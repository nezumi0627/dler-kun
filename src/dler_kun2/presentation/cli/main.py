"""First-party CLI entry point."""

from __future__ import annotations

import argparse
from math import isfinite
from pathlib import Path
from urllib.parse import urlsplit

from dler_kun2.domain.errors import EngineError, ErrorCode
from dler_kun2.infrastructure.http.client import HttpRuntime
from dler_kun2.infrastructure.state.config import ConfigStore
from dler_kun2.presentation.cli.commands import run_command
from dler_kun2.presentation.cli.output import emit
from dler_kun2.routing.defaults import build_registry
from dler_kun2.routing.registry import EngineRegistry, RouteError


def _runtime_from_config(config: dict[str, object]) -> HttpRuntime:
    try:
        timeout = float(config.get("timeout", 30))
        concurrency = int(config.get("threads", 3))
    except (TypeError, ValueError) as exc:
        raise EngineError(ErrorCode.INVALID_REQUEST, "network timeout or thread count is invalid") from exc
    if not isfinite(timeout) or timeout <= 0 or not 1 <= concurrency <= 64:
        raise EngineError(ErrorCode.INVALID_REQUEST, "network timeout or thread count is outside supported bounds")
    proxy_value = config.get("proxy", "")
    proxy = str(proxy_value).strip() if proxy_value else None
    if proxy:
        parsed_proxy = urlsplit(proxy)
        if parsed_proxy.scheme not in {"http", "https", "socks4", "socks5"} or not parsed_proxy.hostname:
            raise EngineError(ErrorCode.INVALID_REQUEST, "configured proxy URL is invalid")
        try:
            parsed_proxy.port
        except ValueError as exc:
            raise EngineError(ErrorCode.INVALID_REQUEST, "configured proxy port is invalid") from exc
    try:
        return HttpRuntime(
            total_timeout=timeout,
            connect_timeout=min(10.0, timeout),
            read_timeout=timeout,
            concurrency=concurrency,
            proxy=proxy,
            cookie=str(config.get("cookie") or "") or None,
            user_agent=str(config.get("user_agent") or "") or None,
            local_addr=str(config.get("local_addr") or "") or None,
        )
    except ValueError as exc:
        raise EngineError(ErrorCode.INVALID_REQUEST, "network configuration is invalid") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dler-kun2")
    parser.add_argument("--json", action="store_true", dest="global_json")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("detect", "sites", "help", "download", "crawl", "ranking", "jobs", "cancel", "config"):
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
            command.add_argument("--single", action="store_true", help="mvfile: download only the requested item")
            command.add_argument("--quality")
            command.add_argument("--god", action="store_true", help="increase bounded transfer concurrency")
        if name in {"download", "crawl", "ranking"}:
            command.add_argument("--metadata", action="store_true")
        if name == "crawl":
            command.add_argument("--overwrite", action="store_true")
            command.add_argument("--god", action="store_true", help="increase bounded crawl/download concurrency")
            command.add_argument("--hls-workers", type=int)
            command.add_argument("--download-attempts", type=int)
            command.add_argument("--download-read-timeout", type=float)
            command.add_argument("--download-max-time", type=float)
            command.add_argument("--discover-workers", type=int)
        if name in {"download", "crawl"}:
            command.add_argument("--parallel-downloads", type=int)
        if name == "download":
            command.add_argument("--hls-workers", type=int)
        if name in {"crawl", "ranking"}:
            command.add_argument("--limit", type=int)
        if name == "crawl":
            command.add_argument("--resolve-workers", type=int)
        if name in {"download", "crawl"}:
            command.add_argument("--segment-concurrency", type=int)
            command.add_argument("--browser-path")
            command.add_argument("--ffmpeg-path")
            command.add_argument("--timeout-seconds", "--timeout", dest="timeout_seconds", type=float)
            command.add_argument("--api-base", help="mvfile/gofilerun API base URL override")
        if name in {"download", "crawl", "ranking"}:
            command.add_argument("--proxy")
            command.add_argument("--user-agent")
            command.add_argument("--cookie")
            command.add_argument("--local-addr")
        if name == "config":
            command.add_argument("--save", action="store_true", help="Write the effective config.json")
        command.add_argument("--json", action="store_true")
        if name in {"download", "crawl", "ranking"}:
            command.add_argument("-o", "--output-dir", type=Path)
        if name == "download":
            command.add_argument("--parallel", "--parallel-urls", dest="parallel_urls", type=int, default=4, help="Maximum URLs downloaded concurrently")
            command.add_argument("--seg-workers", dest="segment_concurrency", type=int)
        if name in {"crawl", "ranking"}:
            command.add_argument("--download", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "help":
        parser.print_help()
        return 0
    json_mode = args.global_json or args.json
    target = getattr(args, "service", getattr(args, "target", None))
    targets = tuple(target) if args.command == "download" else None
    if args.command == "download" and target:
        target = target[0]
    seeds = tuple(getattr(args, "seed", ())) + tuple(getattr(args, "source", ()))
    option_names = ("max_pages", "limit", "password", "segment_concurrency", "hls_workers", "browser_path", "ffmpeg_path", "timeout_seconds", "resolve_workers", "parallel_downloads", "download_attempts", "download_read_timeout", "download_max_time", "discover_workers", "quality", "single", "god", "force", "overwrite", "metadata")
    options = {name: value for name in option_names if (value := getattr(args, name, None)) not in (None, False)}
    if options.get("god"):
        options["resolve_workers"] = max(int(options.get("resolve_workers", 0)), 12)
        options["parallel_downloads"] = max(int(options.get("parallel_downloads", 0)), 8)
        options["hls_workers"] = max(int(options.get("hls_workers", 0)), 8)
        options["segment_concurrency"] = max(int(options.get("segment_concurrency", 0)), 8)
    parallel_urls = getattr(args, "parallel_urls", 4)
    if args.command == "download" and options.get("god"):
        parallel_urls = min(max(parallel_urls, min(len(targets or ()), 16)), 16)
    try:
        config = ConfigStore().as_dict(redact=False)
        if args.command in {"crawl", "ranking"} and target == "gofile":
            gofile_config = config.get("gofile", {})
            if isinstance(gofile_config, dict):
                try:
                    options.setdefault("limit", int(gofile_config.get("ranking_limit", 60)))
                except (TypeError, ValueError) as exc:
                    raise EngineError(ErrorCode.INVALID_REQUEST, "GoFile ranking limit is invalid") from exc
                configured_seeds = gofile_config.get("ranking_seeds")
                if not seeds and configured_seeds:
                    options["config_seeds"] = configured_seeds
        for key in ("proxy", "user_agent", "cookie", "local_addr"):
            override = getattr(args, key, None)
            if override is not None:
                config[key] = override
        timeout_override = getattr(args, "timeout_seconds", None)
        if timeout_override is not None:
            config["timeout"] = timeout_override
        configured_output = config.get("output_dir", "downloads")
        output_dir = getattr(args, "output_dir", None) or Path(str(configured_output))
        mvfile_config = config.get("mvfile", {})
        gofilerun_config = config.get("gofilerun", {})
        mvfile_config = mvfile_config if isinstance(mvfile_config, dict) else {}
        gofilerun_config = gofilerun_config if isinstance(gofilerun_config, dict) else {}
        api_base_override = getattr(args, "api_base", None)
        try:
            registry = build_registry(
                EngineRegistry(),
                http=_runtime_from_config(config),
                mvfile_api_base=api_base_override or str(mvfile_config.get("api_base") or "") or None,
                gofilerun_api_base=api_base_override or str(gofilerun_config.get("api_base") or "") or None,
            )
        except ValueError as exc:
            raise EngineError(ErrorCode.INVALID_REQUEST, "mvfile API base configuration is invalid") from exc
        value = run_command(args.command, target, registry, output_dir=output_dir, download_items=getattr(args, "download", False), seeds=seeds, days=getattr(args, "days", None), save_config=getattr(args, "save", False), cancel_all=getattr(args, "all", False), targets=targets, parallel_urls=parallel_urls, options=options)
    except RouteError as exc:
        value = exc.error
    except EngineError as exc:
        value = exc
    emit(value, json_mode=json_mode)
    return 2 if isinstance(value, EngineError) else 0


if __name__ == "__main__":
    raise SystemExit(main())
