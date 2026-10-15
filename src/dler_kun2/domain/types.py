"""JSON-safe scalar options shared by requests and download plans."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from types import MappingProxyType

EngineOptionValue = str | int | float | bool | None
EngineOptions = Mapping[str, EngineOptionValue]


def freeze_options(options: EngineOptions) -> EngineOptions:
    """Take an immutable snapshot at the engine boundary."""
    values = dict(options)
    for key, value in values.items():
        if not isinstance(key, str) or not (
            value is None or isinstance(value, (str, int, float, bool))
        ) or (isinstance(value, float) and not isfinite(value)):
            raise ValueError("engine options must contain finite JSON scalar values")
    return MappingProxyType(values)
