from __future__ import annotations

from pathlib import Path


def unique_path(target: Path, *, separator: str = "-", start: int = 2) -> Path:
    """Return a path that does not collide case-insensitively with disk."""
    if not _casefold_exists(target):
        return target
    base_stem = target.stem
    suffix = target.suffix
    counter = start
    while True:
        candidate = target.with_name(f"{base_stem}{separator}{counter}{suffix}")
        if not _casefold_exists(candidate):
            return candidate
        counter += 1


def _casefold_exists(target: Path) -> bool:
    if target.exists():
        return True
    try:
        key = target.name.casefold()
        return any(child.name.casefold() == key for child in target.parent.iterdir())
    except OSError:
        return False
