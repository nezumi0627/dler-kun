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
        path = Path(name)
        stem, suffix = path.stem, path.suffix
        identity = hashlib.sha256(plan.source_url.encode("utf-8")).hexdigest()[:10]
        candidate = root / f"{stem}-{identity}{suffix}"
        attempt = 0
        while True:
            try:
                with candidate.open("xb"):
                    pass
                if candidate.resolve().parent != root:
                    candidate.unlink(missing_ok=True)
                    raise ValueError("output path escaped its root")
                return candidate
            except FileExistsError:
                attempt += 1
                candidate = root / f"{stem}-{identity}-{attempt}{suffix}"
