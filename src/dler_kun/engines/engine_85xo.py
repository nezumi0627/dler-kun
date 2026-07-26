"""Importable alias for the ``85xo`` engine package.

The package directory is ``engines/85xo`` (matches ``engine_id``), but Python
identifiers cannot start with a digit, so callers import through this module.
"""

from __future__ import annotations

import importlib
from typing import Any

_engine = importlib.import_module("dler_kun.engines.85xo")
_seeds = importlib.import_module("dler_kun.engines.85xo.seeds")

Engine85xo = _engine.Engine85xo
DEFAULT_85XO_SEEDS = _seeds.DEFAULT_85XO_SEEDS
resolve_85xo_seeds = _seeds.resolve_85xo_seeds

__all__ = [
    "DEFAULT_85XO_SEEDS",
    "Engine85xo",
    "resolve_85xo_seeds",
]


def __getattr__(name: str) -> Any:
    fast = importlib.import_module("dler_kun.engines.85xo.fast")
    if hasattr(fast, name):
        return getattr(fast, name)
    if hasattr(_seeds, name):
        return getattr(_seeds, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
