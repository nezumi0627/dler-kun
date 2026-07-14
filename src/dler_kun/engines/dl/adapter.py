from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ...engine import IDownloader
from ...models import (
    CrawlRequest,
    CrawlResult,
    DownloadRequest,
    DownloadResult,
    EngineCapability,
    JobStatus,
)


class DlEngine(IDownloader):
    engine_id = "dl"
    display_name = "DL Engine"
    capabilities = EngineCapability(download=True, crawl=False, ranking=False)

    def __init__(self, project_path: str | Path | None = None) -> None:
        if project_path:
            self.project_path = Path(project_path)
            self.script_path = self.project_path / "download_twitter_media.py"
        else:
            self.script_path = (
                Path(__file__).resolve().parents[2]
                / "vendor"
                / "dl"
                / "download_twitter_media.py"
            )
            self.project_path = self.script_path.parent

    def detect(self, url: str) -> bool:
        lowered = url.lower()
        return any(
            domain in lowered
            for domain in ("tweetfile.com", "twimg-media.com", "cdn1.twimg-media.com")
        )

    def download(self, request: DownloadRequest) -> DownloadResult:
        if not self.script_path.exists():
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=f"dl script not found: {self.script_path}",
                errors=["dependency_missing"],
            )

        command = [
            sys.executable,
            str(self.script_path),
            request.url,
            "-o",
            str(request.output_dir),
        ]
        if request.options.get("force"):
            command.append("--force")
        if request.options.get("verbose"):
            command.append("--verbose")
        if request.options.get("parallel"):
            command.extend(["-p", str(request.options["parallel"])])
        if request.options.get("seg_workers"):
            command.extend(["-w", str(request.options["seg_workers"])])
        if request.options.get("quality"):
            command.extend(["-q", str(request.options["quality"])])

        completed = subprocess.run(
            command,
            cwd=str(self.project_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
        if completed.returncode == 0:
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.SUCCESS,
                message="dl completed.",
                metadata={"stdout": output[-8000:]},
            )
        return DownloadResult(
            job_id=request.job_id,
            engine_id=self.engine_id,
            status=JobStatus.FAILED,
            message=f"dl failed with exit code {completed.returncode}.",
            errors=[output[-8000:] or "download_failed"],
        )

    def crawl(self, request: CrawlRequest) -> CrawlResult:
        return CrawlResult(
            job_id=request.job_id,
            engine_id=self.engine_id,
            status=JobStatus.UNSUPPORTED,
            message="dl engine has no standalone crawler adapter.",
        )
