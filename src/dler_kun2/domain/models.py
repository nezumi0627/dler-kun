"""Validated partial outcomes shared by download, crawl, and ranking."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import EngineError
from .plans import DownloadPlan


def _validate_counts(
    output_paths: tuple[Path, ...],
    requested: int,
    discovered: int,
    completed: int,
    unavailable: int,
) -> None:
    if min(requested, discovered, completed, unavailable) < 0:
        raise ValueError("result counts must be nonnegative")
    if completed + unavailable > discovered:
        raise ValueError("completed and unavailable cannot exceed discovered")
    if completed != len(output_paths):
        raise ValueError("completed must match output path count")


@dataclass(frozen=True)
class DownloadResult:
    output_paths: tuple[Path, ...] = ()
    requested: int = 0
    discovered: int = 0
    completed: int = 0
    unavailable: int = 0
    errors: tuple[EngineError, ...] = ()
    experimental: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_paths", tuple(self.output_paths))
        object.__setattr__(self, "errors", tuple(self.errors))
        _validate_counts(
            self.output_paths,
            self.requested,
            self.discovered,
            self.completed,
            self.unavailable,
        )


@dataclass(frozen=True)
class CrawlResult:
    plans: tuple[DownloadPlan, ...] = ()
    output_paths: tuple[Path, ...] = ()
    requested: int = 0
    discovered: int = 0
    completed: int = 0
    unavailable: int = 0
    errors: tuple[EngineError, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "plans", tuple(self.plans))
        object.__setattr__(self, "output_paths", tuple(self.output_paths))
        object.__setattr__(self, "errors", tuple(self.errors))
        _validate_counts(
            self.output_paths,
            self.requested,
            self.discovered,
            self.completed,
            self.unavailable,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "plans": [plan.to_dict() for plan in self.plans],
            "output_paths": [str(path) for path in self.output_paths],
            "requested": self.requested,
            "discovered": self.discovered,
            "completed": self.completed,
            "unavailable": self.unavailable,
            "errors": [error.to_dict() for error in self.errors],
        }
