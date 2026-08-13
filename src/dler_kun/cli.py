from __future__ import annotations

import json
import sys
from typing import Any

from .app import to_jsonable


def print_json(value: Any) -> None:
    print(json.dumps(to_jsonable(value), ensure_ascii=False, indent=2))


def print_sites(sites: dict[str, list[str]], *, as_json: bool = False) -> int:
    if as_json:
        print_json(sites)
        return 0
    print("対応済みサイト一覧:")
    for engine_id, domains in sites.items():
        print(f"  {engine_id:<10} {', '.join(domains)}")
    return 0


def print_detect(result: dict[str, Any], *, as_json: bool = False) -> int:
    if as_json:
        print_json(result)
    elif result.get("supported"):
        print(f"[SUCCESS] {result.get('engine_id')}")
    else:
        print(f"[ERROR] {result.get('message') or 'unsupported'}")
    return 0 if result.get("supported") else 1


def print_download_results(
    results: list[dict[str, Any]], *, as_json: bool = False
) -> int:
    if as_json:
        print_json(results)
        return _exit_code_from_statuses(item.get("status") for item in results)

    for result in results:
        status = str(result.get("status", "")).lower()
        url = str(result.get("url") or "").strip()
        message = str(result.get("message") or status).strip()
        files = result.get("files") or []
        errors = result.get("errors") or []
        tag = _status_tag(status)
        file_count = len(files) if isinstance(files, list) else 0

        if status in {"success", "ok", "complete", "completed"}:
            summary = (
                f"Downloaded {file_count} file(s)."
                if file_count
                else (message or "Download completed.")
            )
            if message.startswith("Downloaded "):
                summary = message
            print(f"{tag} {summary}")
        else:
            print(f"{tag} {message}")

        if url:
            print(f"  {url}")
        if errors and status not in {"success", "ok", "complete", "completed"}:
            print(f"  errors: {', '.join(str(error) for error in errors)}")
    return _exit_code_from_statuses(item.get("status") for item in results)


def print_job_result(result: dict[str, Any], *, as_json: bool = False) -> int:
    if as_json:
        print_json(result)
        return _exit_code_from_status(result.get("status"))

    status = str(result.get("status", "")).lower()
    message = result.get("message") or status
    items = result.get("items")
    files = result.get("files") or []
    errors = result.get("errors") or []
    engine_id = result.get("engine_id") or result.get("service") or ""

    tag = _status_tag(status)
    prefix = f"{engine_id}: " if engine_id else ""
    print(f"{tag} {prefix}{message}")
    if isinstance(items, list):
        print(f"  items: {len(items)}")
    if files or "files" in result:
        print(f"  files: {len(files)}")
    if errors:
        print(f"  errors: {', '.join(str(error) for error in errors)}")
    return _exit_code_from_status(status)


def print_cancel_result(result: dict[str, Any], *, as_json: bool = False) -> int:
    if as_json:
        print_json(result)
    else:
        status = str(result.get("status", "")).lower()
        message = result.get("message") or status
        print(f"{_status_tag(status)} {message}")
        job_ids = result.get("job_ids")
        if job_ids:
            print(f"  jobs: {len(job_ids)}")
        elif result.get("job_id"):
            print(f"  job_id: {result['job_id']}")
    return 0 if str(result.get("status", "")).lower() != "unsupported" else 1


def print_config(config: dict[str, Any], *, as_json: bool = True) -> int:
    # config is always machine-oriented; keep JSON as the default view.
    print_json(config)
    return 0


def _status_tag(status: str) -> str:
    normalized = status.lower()
    if normalized in {"success", "ok", "complete", "completed"}:
        return "[SUCCESS]"
    if normalized in {"cancelled", "canceled"}:
        return "[WARNING]"
    if normalized in {"unsupported"}:
        return "[ERROR]"
    if normalized in {"failed", "error", "failure"}:
        return "[ERROR]"
    return "[INFO]"


def _exit_code_from_status(status: Any) -> int:
    normalized = str(status or "").lower()
    if normalized in {
        "success",
        "ok",
        "complete",
        "completed",
        "cancelled",
        "canceled",
    }:
        return 0
    return 1


def _exit_code_from_statuses(statuses) -> int:
    codes = [_exit_code_from_status(status) for status in statuses]
    return 1 if any(codes) else 0


def exit_with(code: int) -> None:
    sys.exit(code)
