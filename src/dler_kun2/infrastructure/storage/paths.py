"""Collision-proof output path allocation under a chosen root."""

import hashlib
import re
from pathlib import Path

from dler_kun2.domain.plans import DownloadPlan

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.I)


def _safe_name(name: str) -> str:
    leaf = name.replace("\\", "/").split("/")[-1].strip().rstrip(".")
    leaf = _INVALID.sub("_", leaf).strip(" .") or "download"
    stem = leaf.split(".", 1)[0]
    if _RESERVED.match(stem) or _RESERVED.match(leaf):
        leaf = f"_{leaf}"
    return leaf[:180]


class OutputAllocator:
    def reserve(
        self, plan: DownloadPlan, root: Path, batch: str | None = None
    ) -> Path:
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        name = _safe_name(plan.suggested_name)
        if batch:
            name = f"{_safe_name(batch)}_{name}"
        relative_dir = plan.metadata.get("relative_dir")
        safe_parts = (
            tuple(_safe_name(part) for part in str(relative_dir).replace("\\", "/").split("/") if part.strip(" ."))
            if isinstance(relative_dir, str) and relative_dir
            else ()
        )
        parent = root.joinpath(*safe_parts)
        if not parent.resolve(strict=False).is_relative_to(root):
            raise ValueError("output path escaped its root")
        parent.mkdir(parents=True, exist_ok=True)
        path = Path(name)
        stem, suffix = path.stem, path.suffix
        stable_id = plan.metadata.get("file_id")
        identity_source = plan.source_url
        if isinstance(stable_id, (str, int)) and str(stable_id):
            identity_source = f"{identity_source}\0{stable_id}"
        identity = hashlib.sha256(identity_source.encode("utf-8")).hexdigest()
        candidate = parent / f"{stem}-{identity}{suffix}"
        attempt = 0
        while True:
            # Re-resolve immediately before creating: an existing symlink inside
            # the output tree must never redirect the reservation elsewhere.
            if not parent.resolve(strict=True).is_relative_to(root):
                raise ValueError("output path escaped its root")
            try:
                with candidate.open("xb"):
                    pass
                if not candidate.resolve().is_relative_to(root):
                    candidate.unlink(missing_ok=True)
                    raise ValueError("output path escaped its root")
                return candidate
            except FileExistsError:
                attempt += 1
                candidate = parent / f"{stem}-{identity}-{attempt}{suffix}"
