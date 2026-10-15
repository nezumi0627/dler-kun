"""Non-destructive migration of small legacy state files."""

import shutil
from pathlib import Path


class StateMigrator:
    FILES = (
        "config.json",
        "history.json",
        "download_cache.json",
        "fast_capture_cache.json",
        "tokens.json",
    )
    DIRECTORIES = ("cache", "cookies", "tokens", "token")

    def migrate(self, old_root: Path, new_root: Path) -> int:
        old_root, new_root = Path(old_root), Path(new_root)
        new_root.mkdir(parents=True, exist_ok=True)
        copied = 0
        for name in self.FILES:
            source, destination = old_root / name, new_root / name
            if source.is_file() and not source.is_symlink():
                copied += 1
                if not destination.exists():
                    shutil.copy2(source, destination)
        for name in self.DIRECTORIES:
            source, destination = old_root / name, new_root / name
            if not source.is_dir() or source.is_symlink():
                continue
            for item in source.rglob("*"):
                if item.is_symlink() or not item.is_file():
                    continue
                target = destination / item.relative_to(source)
                copied += 1
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)
        return copied
