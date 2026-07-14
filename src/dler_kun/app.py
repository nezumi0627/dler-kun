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
    ProgressManager,
    ProxyManager,
    QueueManager,
    RetryManager,
    ThreadPool,
    UpdateChecker,
)
from .models import CrawlRequest, DownloadRequest, JobStatus


class DlerKunApp:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config = ConfigManager(config_path)
        self.logs = LogManager()
        self.history = HistoryManager()
        self.progress = ProgressManager()
        self.queue = QueueManager()
        self.proxy = ProxyManager(self.config)
        self.cookies = CookieManager(self.config)
        self.retry = RetryManager(int(self.config.get("retry", 2)))
        self.thread_pool = ThreadPool(int(self.config.get("threads", 3)))
        self.update_checker = UpdateChecker()
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
            result = detected.download(request)
            self.queue.update(
                queue_job.id,
                status=result.status,
                progress=100 if result.status == JobStatus.SUCCESS else 0,
                error="; ".join(result.errors),
            )
            self.progress.update(
                queue_job.id,
                progress=100 if result.status == JobStatus.SUCCESS else 0,
                state=result.status.value,
            )
            if result.status == JobStatus.SUCCESS:
                self.logs.success(result.message, engine_id=result.engine_id, job_id=result.job_id)
            else:
                self.logs.error(result.message, engine_id=result.engine_id, job_id=result.job_id)
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
            options=options or {},
        )
        self.queue.update(queue_job.id, status=JobStatus.RUNNING)
        self.logs.info("Crawl started", engine_id=engine.engine_id, job_id=queue_job.id)
        result = engine.crawl(request)
        self.queue.update(
            queue_job.id,
            status=result.status,
            progress=100 if result.status == JobStatus.SUCCESS else 0,
            error="; ".join(result.errors),
        )
        if result.status == JobStatus.SUCCESS:
            self.logs.success(result.message, engine_id=result.engine_id, job_id=result.job_id)
        else:
            self.logs.error(result.message, engine_id=result.engine_id, job_id=result.job_id)
        result_dict = to_jsonable(result)
        self.history.append({"kind": "crawl", **result_dict})
        return result_dict

    def snapshot(self) -> dict[str, Any]:
        return {
            "engines": self.factory.list_engines(),
            "queue": self.queue.list(),
            "history": self.history.list(),
            "logs": self.logs.list(),
            "progress": self.progress.list(),
            "config": self.config.as_dict(),
            "supported_domains": self.detector.supported_domains(),
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
