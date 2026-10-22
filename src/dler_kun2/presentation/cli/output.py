"""Stable public CLI output; never reflect private plan fields."""

from __future__ import annotations

import json

from dler_kun2.domain.errors import EngineError
from dler_kun2.domain.models import CrawlResult, DownloadResult


def public_payload(value: object) -> dict[str, object]:
    if isinstance(value, EngineError):
        return {"error": value.to_dict()}
    if isinstance(value, CrawlResult):
        return value.to_dict()
    if isinstance(value, DownloadResult):
        return {"output_paths": [str(path) for path in value.output_paths], "requested": value.requested, "discovered": value.discovered, "completed": value.completed, "unavailable": value.unavailable, "errors": [error.to_dict() for error in value.errors], **({"experimental": True} if value.experimental else {})}
    if isinstance(value, dict):
        return value
    raise TypeError("unsupported public payload")


def emit(value: object, *, json_mode: bool) -> None:
    payload = public_payload(value)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    elif isinstance(value, EngineError):
        print(f"[ERROR] {value.code.value}: {value.message}")
    elif isinstance(value, dict) and "sites" in value:
        sites = value["sites"]
        print("[INFO] No engines registered (migration pending)" if not sites else f"[INFO] {len(sites)} engine(s) registered")
    elif isinstance(value, dict) and "engine_id" in value:
        print(f"[SUCCESS] {value['engine_id']}")
    elif isinstance(value, dict) and "jobs" in value:
        print(f"[INFO] {len(value['jobs'])} job(s)")
    elif isinstance(value, dict) and "cancel_requested" in value:
        label = "requested" if value["cancel_requested"] else "not changed"
        print(f"[INFO] cancellation {label}: {value['job_id']}")
    elif isinstance(value, dict) and "cancelled" in value:
        print(f"[INFO] cancellation requested for {value['cancelled']} job(s)")
    elif isinstance(value, dict) and "config" in value:
        print("[SUCCESS] configuration saved" if value["saved"] else "[INFO] effective configuration")
    elif isinstance(value, (CrawlResult, DownloadResult)):
        prefix = "[EXPERIMENTAL] " if isinstance(value, DownloadResult) and value.experimental else ""
        label = "ERROR" if value.errors and not value.completed else "INFO"
        print(f"{prefix}[{label}] discovered {value.discovered}, completed {value.completed}, unavailable {value.unavailable}, errors {len(value.errors)}")
        for error in value.errors:
            print(f"{prefix}[ERROR] {error.code.value}: {error.message}")
    else:
        print("[INFO] Command completed")
