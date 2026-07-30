from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .detector import ServiceDetector
from .engines.gofile import GoFileEngine
from .engines.mvfile import MvfileEngine
from .engines.twimg import TwimgEngine
from .engines.engine_85xo import Engine85xo, resolve_85xo_seeds
from .engines.gofile.seeds import resolve_gofile_ranking_seeds
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
    def __init__(
        self,
        config_path: Path | None = None,
        *,
        live_progress: bool | None = None,
    ) -> None:
        self.config = ConfigManager(config_path)
        self.logs = LogManager()
        self.history = HistoryManager()
        self.cache = DownloadCacheManager()
        self.progress = ProgressManager(live=live_progress)
        self.queue = QueueManager()
        self.proxy = ProxyManager(self.config)
        self.cookies = CookieManager(self.config)
        self.retry = RetryManager(int(self.config.get("retry", 2)))
        self.detector = ServiceDetector()
        self.factory = DownloaderFactory(self.detector)
        self._register_engines()

    def _register_engines(self) -> None:
        engine_paths = self.config.get("engine_paths", {})
        self.factory.register(TwimgEngine(engine_paths.get("twimg") or None))
        self.factory.register(
            GoFileEngine(
                engine_paths.get("gofile") or None,
                proxy=self.proxy.get_proxy(),
            )
        )
        self.factory.register(Engine85xo(engine_paths.get("85xo") or None))
        self.factory.register(MvfileEngine(engine_paths.get("mvfile") or None))

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
        base_options = {
            **(options or {}),
            "cache_manager": self.cache,
            "user_agent": str(
                (options or {}).get("user_agent")
                or self.config.get("user_agent", "")
                or ""
            ),
            "cookie": str(
                (options or {}).get("cookie") or self.cookies.get_cookie() or ""
            ),
        }
        results: list[dict[str, Any]] = []
        self.progress.start_live()
        try:
            for url in urls:
                detected = self.factory.detect(url)
                if not detected:
                    self.logs.warning(
                        "対応サービスではありません", engine_id=None, url=url
                    )
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
                    options={
                        **base_options,
                        **self._engine_download_options(detected.engine_id),
                        "progress_callback": lambda state, job_id=queue_job.id: (
                            self._update_job_progress(job_id, state)
                        ),
                    },
                )
                self.queue.update(queue_job.id, status=JobStatus.RUNNING)
                self.progress.update(
                    queue_job.id,
                    completed_files=0,
                    total_files=1,
                    current_file=_short_label(url),
                    state="running",
                )
                self.logs.info(
                    "Download started",
                    engine_id=detected.engine_id,
                    job_id=queue_job.id,
                )
                try:
                    self._raise_if_cancelled(queue_job.id)
                    result = self._run_download_with_retry(detected, request)
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
                cancelled = self._finish_job(
                    result.job_id,
                    result.status,
                    result.message,
                    result.engine_id,
                    result.errors,
                )
                if cancelled is not None:
                    cancelled["url"] = url
                    results.append(cancelled)
                    self.history.append({"kind": "download", **cancelled})
                    continue
                result_dict = to_jsonable(result)
                result_dict["url"] = url
                results.append(result_dict)
                self.history.append({"kind": "download", **result_dict})
        finally:
            self.progress.close_live()
        return results

    def crawl(
        self,
        service: str,
        output_dir: str | Path | None = None,
        seeds: list[str] | None = None,
        days: int | None = None,
        download: bool = False,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        engine = self.factory.get(service)
        output = Path(output_dir or self.config.get("output_dir", "downloads"))
        options = dict(options or {})
        if not engine:
            return {
                "service": service,
                "status": JobStatus.UNSUPPORTED.value,
                "message": "対応サービスではありません",
            }
        # GoFile crawl is ranking under another name; avoid creating an orphan crawl job.
        if service == "gofile":
            return self.ranking(
                service=service,
                output_dir=output,
                seeds=seeds,
                download=download,
                options=options,
            )
        queue_job = self.queue.create("crawl", engine.engine_id, service, str(output))
        seeds_list = list(seeds or [])
        resolved_days = days or 10
        if service == "85xo":
            config_85xo = self.config.get("85xo", {})
            resolved_days = int(days or config_85xo.get("days", 10))
            options.setdefault("max_pages", int(config_85xo.get("max_pages", 50)))
            options.setdefault(
                "network_capture_seconds",
                float(config_85xo.get("network_capture_seconds", 15.0)),
            )
            options.setdefault("user_agent", self.config.get("user_agent", ""))
            seeds_list = resolve_85xo_seeds(
                seeds_list,
                option_seed=options.get("seed"),
                config_seeds=config_85xo.get("default_seeds"),
                legacy_config_seed=config_85xo.get("default_seed"),
            )
        if service == "mvfile":
            mvfile_config = self.config.get("mvfile", {})
            options.setdefault("api_base", mvfile_config.get("api_base"))
            options.setdefault(
                "timeout_seconds",
                float(mvfile_config.get("timeout_seconds", 30.0)),
            )
            if not seeds_list and options.get("seed"):
                seeds_list = [str(options["seed"])]
        request = CrawlRequest(
            service=service,
            output_dir=output,
            job_id=queue_job.id,
            seeds=seeds_list,
            days=resolved_days,
            download=download,
            options={
                **options,
                "cache_manager": self.cache,
                "progress_callback": lambda state: self._update_job_progress(
                    queue_job.id,
                    state,
                ),
            },
        )
        self.queue.update(queue_job.id, status=JobStatus.RUNNING)
        self.progress.update(queue_job.id, progress=0, state="running", label=service)
        self.logs.info("Crawl started", engine_id=engine.engine_id, job_id=queue_job.id)
        self.progress.start_live()
        try:
            try:
                self._raise_if_cancelled(queue_job.id)
                result = self._run_crawl_with_retry(engine, request)
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
            cancelled = self._finish_job(
                result.job_id,
                result.status,
                result.message,
                result.engine_id,
                result.errors,
            )
            if cancelled is not None:
                cancelled["service"] = service
                self.history.append({"kind": "crawl", **cancelled})
                return cancelled
            result_dict = to_jsonable(result)
            self.history.append({"kind": "crawl", **result_dict})
            return result_dict
        finally:
            self.progress.close_live()

    def ranking(
        self,
        service: str,
        output_dir: str | Path | None = None,
        seeds: list[str] | None = None,
        download: bool = False,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        engine = self.factory.get(service)
        output = Path(output_dir or self.config.get("output_dir", "downloads"))
        options = dict(options or {})
        if not engine:
            return {
                "service": service,
                "status": JobStatus.UNSUPPORTED.value,
                "message": "対応サービスではありません",
            }

        queue_job = self.queue.create("ranking", engine.engine_id, service, str(output))
        seeds_list = list(seeds or [])

        if service == "gofile":
            gofile_config = self.config.get("gofile", {})
            options.setdefault("limit", int(gofile_config.get("ranking_limit", 60)))
            options.setdefault(
                "max_more_clicks",
                int(gofile_config.get("max_more_clicks", 5)),
            )
            options.setdefault("user_agent", self.config.get("user_agent", ""))
            options.setdefault(
                "config_seeds",
                gofile_config.get("ranking_seeds"),
            )
            resolved = resolve_gofile_ranking_seeds(
                seeds_list,
                option_seed=options.get("seed"),
                config_seeds=options.get("config_seeds"),
                sources=options.get("sources"),
            )
            seeds_list = resolved
            source_flags = _gofile_source_flags(resolved, options.get("sources"))
            options.update(source_flags)

        request = CrawlRequest(
            service=service,
            output_dir=output,
            job_id=queue_job.id,
            seeds=seeds_list,
            download=download,
            options={
                **options,
                "cache_manager": self.cache,
                "progress_callback": lambda state: self._update_job_progress(
                    queue_job.id,
                    state,
                ),
            },
        )
        self.queue.update(queue_job.id, status=JobStatus.RUNNING)
        self.progress.update(queue_job.id, progress=0, state="running", label=service)
        self.logs.info(
            "Ranking started", engine_id=engine.engine_id, job_id=queue_job.id
        )
        self.progress.start_live()
        try:
            try:
                self._raise_if_cancelled(queue_job.id)
                result = self._run_ranking_with_retry(engine, request)
                self._raise_if_cancelled(queue_job.id)
            except JobCancelled:
                result_dict = self._cancel_result(
                    queue_job.id,
                    engine.engine_id,
                    "Ranking cancelled",
                    service=service,
                )
                self.history.append({"kind": "ranking", **result_dict})
                return result_dict
            cancelled = self._finish_job(
                result.job_id,
                result.status,
                result.message,
                result.engine_id,
                result.errors,
            )
            if cancelled is not None:
                cancelled["service"] = service
                self.history.append({"kind": "ranking", **cancelled})
                return cancelled
            result_dict = to_jsonable(result)
            self.history.append({"kind": "ranking", **result_dict})
            return result_dict
        finally:
            self.progress.close_live()

    def _finish_job(
        self,
        job_id: str,
        status: JobStatus,
        message: str,
        engine_id: str,
        errors: list[str],
    ) -> dict[str, Any] | None:
        if self.queue.is_cancelled(job_id):
            return self._cancel_result(job_id, engine_id, message or "Job cancelled")
        progress = 100 if status == JobStatus.SUCCESS else 0
        self.queue.update(
            job_id,
            status=status,
            progress=progress,
            error="; ".join(errors),
        )
        self.progress.finish(
            job_id,
            ok=status == JobStatus.SUCCESS,
            progress=progress,
            state=status.value,
        )
        log = self.logs.success if status == JobStatus.SUCCESS else self.logs.error
        log(message, engine_id=engine_id, job_id=job_id)
        return None

    def _engine_download_options(self, engine_id: str) -> dict[str, Any]:
        if engine_id != "mvfile":
            return {}
        mvfile_config = self.config.get("mvfile", {})
        options: dict[str, Any] = {}
        if mvfile_config.get("api_base"):
            options["api_base"] = mvfile_config.get("api_base")
        if "timeout_seconds" in mvfile_config:
            options["timeout_seconds"] = float(mvfile_config.get("timeout_seconds", 30.0))
        return options

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
        self.progress.finish(
            job_id,
            ok=False,
            progress=0,
            state=JobStatus.CANCELLED.value,
        )
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

    def _run_download_with_retry(
        self,
        engine: Any,
        request: DownloadRequest,
    ) -> Any:
        result = engine.download(request)
        retryable = {"download_failed", "network_error"}
        for _ in range(max(0, self.retry.attempts)):
            if result.status != JobStatus.FAILED:
                break
            if not retryable.intersection(result.errors):
                break
            result = engine.download(request)
        return result

    def _run_crawl_with_retry(
        self,
        engine: Any,
        request: CrawlRequest,
    ) -> Any:
        result = engine.crawl(request)
        retryable = {"crawl_failed", "network_error"}
        for _ in range(max(0, self.retry.attempts)):
            if result.status != JobStatus.FAILED:
                break
            if not retryable.intersection(result.errors):
                break
            result = engine.crawl(request)
        return result

    def _run_ranking_with_retry(
        self,
        engine: Any,
        request: CrawlRequest,
    ) -> Any:
        result = engine.ranking(request)
        retryable = {"crawl_failed", "network_error"}
        for _ in range(max(0, self.retry.attempts)):
            if result.status != JobStatus.FAILED:
                break
            if not retryable.intersection(result.errors):
                break
            result = engine.ranking(request)
        return result

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self.queue.cancel(job_id)
        if not job:
            return {
                "job_id": job_id,
                "status": JobStatus.UNSUPPORTED.value,
                "message": "job not found",
            }
        return self._cancel_result(job_id, job.engine_id, "Job cancelled")

    def cancel_all(self) -> dict[str, Any]:
        jobs = self.queue.cancel_all()
        cancelled_ids = [job.id for job in jobs if self.queue.is_cancelled(job.id)]
        for job_id in cancelled_ids:
            self.progress.finish(
                job_id,
                ok=False,
                progress=0,
                state=JobStatus.CANCELLED.value,
            )
        self.logs.warning("All jobs cancelled", engine_id=None, job_id=None)
        return {
            "status": JobStatus.CANCELLED.value,
            "message": "All jobs cancelled",
            "job_ids": cancelled_ids,
        }


def _gofile_source_flags(
    resolved_seeds: list[str],
    sources: list[str] | None,
) -> dict[str, bool]:
    from .engines.gofile.seeds import classify_ranking_seed, expand_source_aliases

    candidates: list[str] = []
    if sources:
        candidates = expand_source_aliases(
            [str(source) for source in sources if str(source).strip()]
        )
    if not candidates and resolved_seeds:
        candidates = list(resolved_seeds)
    if not candidates:
        return {"douga_enabled": True, "lab_enabled": True}

    has_douga = any(classify_ranking_seed(seed) == "douga" for seed in candidates)
    has_lab = any(classify_ranking_seed(seed) == "lab" for seed in candidates)
    if has_douga and not has_lab:
        return {"douga_enabled": True, "lab_enabled": False}
    if has_lab and not has_douga:
        return {"douga_enabled": False, "lab_enabled": True}
    return {"douga_enabled": True, "lab_enabled": True}


def _short_label(url: str, max_len: int = 48) -> str:
    text = str(url or "").strip()
    if "gofile.io/d/" in text.lower():
        return text.rstrip("/").rsplit("/", 1)[-1]
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat") and callable(value.isoformat):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            return str(value)
    return value
