from __future__ import annotations

import re
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from ...engine import IDownloader
from ...models import (
    DownloadRequest,
    DownloadResult,
    EngineCapability,
    JobStatus,
)

VIDEY_ID_RE = re.compile(r'videy["\']?\s*[:=]\s*["\']([A-Za-z0-9]+)["\']')
CDN_URL = "https://cdn.videy.co/{vid}.mp4"
DOMAINS = ("video.twimg.news", "videy.co")


class VideyEngine(IDownloader):
    engine_id = "videy"
    display_name = "Videy Engine"
    capabilities = EngineCapability(download=True, crawl=False, ranking=False)

    def __init__(self, project_path: str | Path | None = None) -> None:
        self.project_path = Path(project_path) if project_path else Path(__file__).resolve().parent

    def detect(self, url: str) -> bool:
        host = (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower()
        return any(host == d or host.endswith(f".{d}") for d in DOMAINS)

    def download(self, request: DownloadRequest) -> DownloadResult:
        try:
            html = self._fetch_page(request.url)
        except Exception as exc:  # noqa: BLE001
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=str(exc),
                errors=["network_error"],
            )
        ids = list(dict.fromkeys(VIDEY_ID_RE.findall(html)))
        if not ids:
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message="videy media not found.",
                errors=["not_found"],
            )
        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        force = bool(request.options.get("force", False))
        files: list[str] = []
        errors: list[str] = []
        for vid in ids:
            dest = output_dir / f"{vid}.mp4"
            if dest.exists() and dest.stat().st_size > 1024 and not force:
                files.append(str(dest))
                continue
            try:
                self._download(vid, dest)
                files.append(str(dest))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{vid}: {exc}")
        status = JobStatus.SUCCESS if files and not errors else JobStatus.FAILED
        return DownloadResult(
            job_id=request.job_id,
            engine_id=self.engine_id,
            status=status,
            message=(
                f"videy download completed: {len(files)}/{len(ids)} file(s)."
                if files
                else "videy download failed."
            ),
            files=files,
            errors=["download_failed"] if errors else [],
            metadata={"videos": len(ids), "failed": errors[:20]},
        )

    def _fetch_page(self, url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode("utf-8", "replace")

    def _download(self, vid: str, dest: Path) -> None:
        req = urllib.request.Request(CDN_URL.format(vid=vid), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=180) as resp, open(dest, "wb") as f:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
