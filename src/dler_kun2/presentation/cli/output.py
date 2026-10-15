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
        return {"output_paths": [str(path) for path in value.output_paths], "requested": value.requested, "discovered": value.discovered, "completed": value.completed, "unavailable": value.unavailable, "errors": [error.to_dict() for error in value.errors]}
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
        print("[INFO] No engines registered (migration pending)" if not sites else f"[INFO] {sites}")
    else:
        print(f"[INFO] {payload}")
