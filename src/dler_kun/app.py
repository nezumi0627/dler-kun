from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .detector import ServiceDetector
from .engines.dl import DlEngine
from .engines.gofile import GoFileEngine
from .engines.xo85 import Xo85Engine
from .factory import DownloaderFactory
from .managers import (
    ConfigManager,
    CookieManager,
    HistoryManager,
    LogManager,
    DownloadCacheManager,
    ProgressManager,
    ProxyManager,
    QueueManager,
    RetryManager,
)
from .models import CrawlRequest, DownloadRequest, JobStatus


class JobCancelled(RuntimeError):
    """Raised internally when a user cancels a running job."""


class DlerKunApp:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config = ConfigManager(config_path)
        self.logs = LogManager()
        self.history = HistoryManager()
        self.cache = DownloadCacheManager()
        self.progress = ProgressManager()
        self.queue = QueueManager()
        self.proxy = ProxyManager(self.config)
        self.cookies = CookieManager(self.config)
        self.retry = RetryManager(int(self.config.get("retry", 2)))
        self.detector = ServiceDetector()
        self.factory = DownloaderFactory(self.detector)
        self._register_engines()

    def _register_engines(self) -> None:
        engine_paths = self.config.get("engine_paths", {})
        self.factory.register(DlEngine(engine_paths.get("dl") or None))
        self.factory.register(
            GoFileEngine(
                engine_paths.get("gofile") or None,
                proxy=self.proxy.get_proxy(),
            )
        )
        self.factory.register(Xo85Engine(engine_paths.get("85xo") or None))

    def detect(self, url: str) -> dict[str, Any]:
        engine_id = self.detector.detect(url)
        return {
            "url": url,
            "engine_id": engine_id,
            "supported": engine_id is not None,
            "message": engine_id or "対応サービスではありません",
        }

    def download_urls(
        self,
        urls: list[str],
        output_dir: str | Path | None = None,
        options: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        output = Path(output_dir or self.config.get("output_dir", "downloads"))
        options = options or {}
        results: list[dict[str, Any]] = []
        for url in urls:
            detected = self.factory.detect(url)
            if not detected:
                self.logs.warning("対応サービスではありません", engine_id=None, url=url)
                results.append(
                    {
                        "url": url,
                        "status": JobStatus.UNSUPPORTED.value,
                        "message": "対応サービスではありません",
                    }
                )
                continue

            queue_job = self.queue.create(
                "download", detected.engine_id, url, str(output)
            )
            request = DownloadRequest(
                url=url,
                output_dir=output,
                job_id=queue_job.id,
                engine_id=detected.engine_id,
                options=options,
            )
            self.queue.update(queue_job.id, status=JobStatus.RUNNING)
            self.progress.update(queue_job.id, progress=0, state="running")
            self.logs.info("Download started", engine_id=detected.engine_id, job_id=queue_job.id)
            try:
                self._raise_if_cancelled(queue_job.id)
                result = detected.download(request)
                self._raise_if_cancelled(queue_job.id)
            except JobCancelled:
                result_dict = self._cancel_result(
                    queue_job.id,
                    detected.engine_id,
                    "Download cancelled",
                    url=url,
                )
                results.append(result_dict)
                self.history.append({"kind": "download", **result_dict})
                continue
            self._finish_job(
                result.job_id,
                result.status,
                result.message,
                result.engine_id,
                result.errors,
            )
            result_dict = to_jsonable(result)
            result_dict["url"] = url
            results.append(result_dict)
            self.history.append({"kind": "download", **result_dict})
        return results

    def crawl(
        self,
        service: str,
        output_dir: str | Path | None = None,
        seeds: list[str] | None = None,
        days: int = 10,
        download: bool = False,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        engine = self.factory.get(service)
        output = Path(output_dir or self.config.get("output_dir", "downloads"))
        if not engine:
            return {
                "service": service,
                "status": JobStatus.UNSUPPORTED.value,
                "message": "対応サービスではありません",
            }
        queue_job = self.queue.create("crawl", engine.engine_id, service, str(output))
        request = CrawlRequest(
            service=service,
            output_dir=output,
            job_id=queue_job.id,
            seeds=seeds or [],
            days=days,
            download=download,
            options={
                **(options or {}),
                "cache_path": str(self.cache.path),
                "progress_callback": lambda state: self._update_job_progress(
                    queue_job.id,
                    state,
                ),
            },
        )
        self.queue.update(queue_job.id, status=JobStatus.RUNNING)
        self.logs.info("Crawl started", engine_id=engine.engine_id, job_id=queue_job.id)
        try:
            self._raise_if_cancelled(queue_job.id)
            result = engine.crawl(request)
            self._raise_if_cancelled(queue_job.id)
        except JobCancelled:
            result_dict = self._cancel_result(
                queue_job.id,
                engine.engine_id,
                "Crawl cancelled",
                service=service,
            )
            self.history.append({"kind": "crawl", **result_dict})
            return result_dict
        self._finish_job(
            result.job_id,
            result.status,
            result.message,
            result.engine_id,
            result.errors,
        )
        result_dict = to_jsonable(result)
        self.history.append({"kind": "crawl", **result_dict})
        return result_dict

    def _finish_job(
        self,
        job_id: str,
        status: JobStatus,
        message: str,
        engine_id: str,
        errors: list[str],
    ) -> None:
        if self.queue.is_cancelled(job_id):
            self._cancel_result(job_id, engine_id, message or "Job cancelled")
            return
        progress = 100 if status == JobStatus.SUCCESS else 0
        self.queue.update(
            job_id,
            status=status,
            progress=progress,
            error="; ".join(errors),
        )
        self.progress.update(job_id, progress=progress, state=status.value)
        log = self.logs.success if status == JobStatus.SUCCESS else self.logs.error
        log(message, engine_id=engine_id, job_id=job_id)

    def _update_job_progress(self, job_id: str, state: dict[str, Any]) -> None:
        self._raise_if_cancelled(job_id)
        self.progress.update(job_id, **state)
        self.queue.update(
            job_id,
            progress=float(state.get("progress", 0) or 0),
            speed=str(state.get("speed", "") or ""),
            eta=str(state.get("eta", "") or ""),
        )
        self._raise_if_cancelled(job_id)

    def _raise_if_cancelled(self, job_id: str) -> None:
        if self.queue.is_cancelled(job_id):
            raise JobCancelled(job_id)

    def _cancel_result(
        self,
        job_id: str,
        engine_id: str,
        message: str,
        **extra: Any,
    ) -> dict[str, Any]:
        self.queue.cancel(job_id)
        self.progress.update(job_id, progress=0, state=JobStatus.CANCELLED.value)
        self.logs.warning(message, engine_id=engine_id, job_id=job_id)
        return {
            "job_id": job_id,
            "engine_id": engine_id,
            "status": JobStatus.CANCELLED.value,
            "message": message,
            "files": [],
            "errors": [],
            **extra,
        }

def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Path):
        return str(value)
    return value
