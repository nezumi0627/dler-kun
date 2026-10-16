"""JSON-safe scalar options shared by requests and download plans."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from types import MappingProxyType

from .errors import EngineError, ErrorCode

EngineOptionValue = str | int | float | bool | None
EngineOptions = Mapping[str, EngineOptionValue]


def int_option(options: EngineOptions, name: str, default: int) -> int:
    """Read a JSON scalar option as an integer, preserving engine validation."""
    value = options.get(name, default)
    if value is None:
        return default
    try:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (str, int, float)):
            return int(value)
    except (OverflowError, ValueError) as exc:
        raise EngineError(ErrorCode.INVALID_REQUEST, f"{name} must be an integer") from exc
    raise EngineError(ErrorCode.INVALID_REQUEST, f"{name} must be an integer")


def float_option(options: EngineOptions, name: str, default: float) -> float:
    """Read a JSON scalar option as a float."""
    value = options.get(name, default)
    if value is None:
        return default
    try:
        if isinstance(value, bool):
            number = float(value)
        elif isinstance(value, (str, int, float)):
            number = float(value)
        else:
            raise TypeError
    except (OverflowError, TypeError, ValueError) as exc:
        raise EngineError(ErrorCode.INVALID_REQUEST, f"{name} must be a number") from exc
    if not isfinite(number):
        raise EngineError(ErrorCode.INVALID_REQUEST, f"{name} must be a finite number")
    return number


def freeze_options(options: EngineOptions) -> EngineOptions:
    """Take an immutable snapshot at the engine boundary."""
    values = dict(options)
    for key, value in values.items():
        if not isinstance(key, str) or not (
            value is None or isinstance(value, (str, int, float, bool))
        ) or (isinstance(value, float) and not isfinite(value)):
            raise ValueError("engine options must contain finite JSON scalar values")
    return MappingProxyType(values)
