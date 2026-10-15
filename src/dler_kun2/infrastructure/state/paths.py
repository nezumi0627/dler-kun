"""Per-user application state directory selection."""

from __future__ import annotations

import os
from pathlib import Path


def state_dir() -> Path:
    override = os.environ.get("DLER_KUN2_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "dler-kun2"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "dler-kun2"
