from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from ...engine import IDownloader
from ...models import (
    DownloadRequest,
    DownloadResult,
    EngineCapability,
    JobStatus,
)
from ...net import fetch_text

VIDEY_ID_RE = re.compile(r'videy["\']?\s*[:=]\s*["\']([A-Za-z0-9]+)["\']')
CDN_URL = "https://cdn.videy.co/{vid}.mp4"
DOMAINS = ("video.twimg.news", "videy.co")


class VideyEngine(IDownloader):
    engine_id = "videy"
    display_name = "Videy Engine"
    capabilities = EngineCapability(download=True, crawl=False, ranking=False)

    def detect(self, url: str) -> bool:
        host = (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower()
        return any(host == d or host.endswith(f".{d}") for d in DOMAINS)

    def download(self, request: DownloadRequest) -> DownloadResult:
        local_addr = str(request.options.get("local_addr") or "")
        proxy = str(request.options.get("proxy") or "")
        try:
            html = self._fetch_page(request.url, local_addr=local_addr, proxy=proxy)
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
                self._download(vid, dest, local_addr=local_addr, proxy=proxy)
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

    def _fetch_page(self, url: str, local_addr: str = "", proxy: str = "") -> str:
        return fetch_text(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            local_addr=local_addr,
            proxy=proxy,
            timeout_seconds=60,
        )

    def _download(self, vid: str, dest: Path, local_addr: str = "", proxy: str = "") -> None:
        from ...net import curl_download

        curl_download(
            CDN_URL.format(vid=vid),
            dest,
            headers={"User-Agent": "Mozilla/5.0"},
            local_addr=local_addr,
            proxy=proxy,
            read_timeout_seconds=180,
        )
