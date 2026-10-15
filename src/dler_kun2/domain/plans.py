"""Internal media transfer plans with a safe public representation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .types import EngineOptionValue, freeze_options


@dataclass(frozen=True)
class DownloadPlan:
    media_url: str = field(repr=False)
    source_url: str
    source_page: str
    media_kind: str
    suggested_name: str
    size: int | None
    metadata: Mapping[str, EngineOptionValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_options(self.metadata))
        if self.size is not None and self.size < 0:
            raise ValueError("size must be nonnegative")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_url": self.source_url,
            "source_page": self.source_page,
            "media_kind": self.media_kind,
            "suggested_name": self.suggested_name,
            "size": self.size,
            "metadata": dict(self.metadata),
        }
