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

    @staticmethod
    def _reject_symlink_components(path: Path) -> None:
        for component in reversed(path.parents):
            if component.is_symlink():
                raise ValueError("state migration destination cannot contain symlinks")
        if path.is_symlink():
            raise ValueError("state migration destination cannot contain symlinks")

    @classmethod
    def _validate_target(cls, root: Path, target: Path) -> None:
        try:
            relative = target.relative_to(root)
        except ValueError as exc:
            raise ValueError("state migration target escaped destination root") from exc
        current = root
        cls._reject_symlink_components(root)
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("state migration destination cannot contain symlinks")
        if not target.resolve(strict=False).is_relative_to(root):
            raise ValueError("state migration target escaped destination root")

    def migrate(self, old_root: Path, new_root: Path) -> int:
        old_root, new_root = Path(old_root), Path(new_root).absolute()
        self._reject_symlink_components(new_root)
        new_root.mkdir(parents=True, exist_ok=True)
        root = new_root.resolve()
        copied = 0
        for name in self.FILES:
            source, destination = old_root / name, root / name
            self._validate_target(root, destination)
            if source.is_file() and not source.is_symlink():
                copied += 1
                if not destination.exists():
                    shutil.copy2(source, destination)
        for name in self.DIRECTORIES:
            source, destination = old_root / name, root / name
            self._validate_target(root, destination)
            if not source.is_dir() or source.is_symlink():
                continue
            for item in source.rglob("*"):
                if item.is_symlink() or not item.is_file():
                    continue
                target = destination / item.relative_to(source)
                self._validate_target(root, target)
                copied += 1
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)
        return copied
