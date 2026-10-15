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


class TwimgEngine(IDownloader):
    engine_id = "twimg"
    display_name = "Twimg Engine"
    capabilities = EngineCapability(download=True, crawl=False, ranking=False)

    def __init__(self, project_path: str | Path | None = None) -> None:
        if project_path:
            self.project_path = Path(project_path)
            self.script_path = self.project_path / "download_twitter_media.py"
        else:
            self.script_path = (
                Path(__file__).resolve().parents[2]
                / "vendor"
                / "twimg"
                / "download_twitter_media.py"
            )
            self.project_path = self.script_path.parent

    def detect(self, url: str) -> bool:
        lowered = url.lower()
        return any(
            domain in lowered
            for domain in (
                "tweetfile.com",
                "twimg-media.com",
                "cdn1.twimg-media.com",
                "twimg.jp",
            )
        )

    def download(self, request: DownloadRequest) -> DownloadResult:
        if not self.script_path.exists():
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=f"twimg script not found: {self.script_path}",
                errors=["dependency_missing"],
            )

        command = [
            sys.executable,
            str(self.script_path),
            request.url,
            "-o",
            str(request.output_dir),
        ]
        request.output_dir.mkdir(parents=True, exist_ok=True)
        before = {
            path.resolve()
            for path in request.output_dir.rglob("*")
            if path.is_file()
        }
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
        local_addr = str(request.options.get("local_addr") or "")
        if local_addr:
            command.extend(["--local-addr", local_addr])

        try:
            completed = subprocess.run(
                command,
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except FileNotFoundError as exc:
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=f"Required downloader dependency is missing: {exc.filename or 'python'}",
                errors=["dependency_missing"],
            )
        if completed.returncode == 0:
            files = sorted(
                str(path)
                for path in request.output_dir.rglob("*")
                if path.is_file() and path.resolve() not in before
            )
            if not files:
                return DownloadResult(
                    job_id=request.job_id,
                    engine_id=self.engine_id,
                    status=JobStatus.FAILED,
                    message="twimg exited successfully without creating media files.",
                    errors=["download_failed"],
                )
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.SUCCESS,
                message="twimg completed.",
                files=files,
            )
        return DownloadResult(
            job_id=request.job_id,
            engine_id=self.engine_id,
            status=JobStatus.FAILED,
            message=f"twimg failed with exit code {completed.returncode}.",
            errors=["download_failed"],
        )

    def crawl(self, request: CrawlRequest) -> CrawlResult:
        return CrawlResult(
            job_id=request.job_id,
            engine_id=self.engine_id,
            status=JobStatus.UNSUPPORTED,
            message="twimg engine has no standalone crawler adapter.",
        )
