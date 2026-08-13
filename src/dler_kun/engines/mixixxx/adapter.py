from __future__ import annotations

import sys
import threading
from pathlib import Path

from ...engine import IDownloader
from ...models import (
    CrawlItem,
    CrawlRequest,
    CrawlResult,
    DownloadRequest,
    DownloadResult,
    EngineCapability,
    JobStatus,
)
from .fast import (
    MixiSession,
    discover_video_pages,
    extract_embed_url,
    fetch_html,
)


class MixixxxEngine(IDownloader):
    engine_id = "mixixxx"
    display_name = "mixixxx Engine"
    capabilities = EngineCapability(download=True, crawl=True, ranking=False)

    def __init__(self, project_path: str | Path | None = None) -> None:
        self.project_path = (
            Path(project_path)
            if project_path
            else Path(__file__).resolve().parents[2] / "vendor" / "85xo"
        )
        self.lib_path = self.project_path

    def detect(self, url: str) -> bool:
        return url.lower().startswith(("https://mixi-xxx.cc/", "http://mixi-xxx.cc/"))

    def download(self, request: DownloadRequest) -> DownloadResult:
        self._ensure_path()
        try:
            output_dir = Path(request.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            page_html = fetch_html(
                request.url,
                float(request.options.get("timeout_seconds", 30.0)),
            )
            embed_url = extract_embed_url(page_html)
            if not embed_url:
                return DownloadResult(
                    job_id=request.job_id,
                    engine_id=self.engine_id,
                    status=JobStatus.FAILED,
                    message="mixi-xxx: embed URL not found.",
                    errors=["not_found"],
                )
            title = request.url.rstrip("/").rsplit("/", 1)[-1]
            target = _safe_path(output_dir, title, ".mp4")
            with MixiSession(
                browser_path=request.options.get("browser_path"),
                timeout_seconds=float(
                    request.options.get("timeout_seconds", 60.0)
                ),
            ) as session:
                result = session.download(
                    embed_url,
                    target,
                    on_progress=request.options.get("progress_callback"),
                    segment_concurrency=int(
                        request.options.get("segment_concurrency", 4)
                    ),
                )
            if not result:
                return DownloadResult(
                    job_id=request.job_id,
                    engine_id=self.engine_id,
                    status=JobStatus.FAILED,
                    message="mixi-xxx: download failed.",
                    errors=["download_failed"],
                )
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.SUCCESS,
                message=f"mixi-xxx download completed: {result}.",
                files=[str(result)],
                errors=[],
                metadata={"embed_url": embed_url},
            )
        except Exception as exc:  # noqa: BLE001 - adapter normalizes engine failures.
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=f"mixi-xxx download failed: {exc}",
                errors=["download_failed"],
            )

    def crawl(self, request: CrawlRequest) -> CrawlResult:
        self._ensure_path()
        try:
            seed = "https://mixi-xxx.cc/"
            if request.seeds:
                seed = str(request.seeds[0])
            if request.options.get("seed"):
                seed = str(request.options["seed"])
            if request.options.get("sources"):
                seed = str(request.options["sources"][0])
            max_pages = int(request.options.get("max_pages", 5))
            pages = discover_video_pages(
                seed,
                max_pages,
                timeout_seconds=float(request.options.get("timeout_seconds", 30.0)),
            )
            limit = request.options.get("limit")
            if limit:
                pages = pages[: int(limit)]
            crawl_items = [
                CrawlItem(
                    url=url,
                    title=title,
                    published_at=None,
                    downloadable=True,
                    metadata={"source": "mixi-xxx listing"},
                )
                for url, title in pages
            ]
            files: list[str] = []
            status = JobStatus.SUCCESS
            errors: list[str] = []
            if request.download and pages:
                output_dir = Path(request.output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                stop_event = request.options.get("stop_event")
                workers = max(1, int(request.options.get("parallel_downloads", 3)))
                session_options = {
                    "browser_path": request.options.get("browser_path"),
                    "timeout_seconds": float(
                        request.options.get("timeout_seconds", 60.0)
                    ),
                }
                page_timeout = float(request.options.get("timeout_seconds", 30.0))
                segment_concurrency = int(
                    request.options.get("segment_concurrency", 4)
                )
                progress_callback = request.options.get("progress_callback")

                def process(pages_slice: list[tuple[str, str]]) -> list[str]:
                    done: list[str] = []
                    with MixiSession(**session_options) as session:
                        for url, title in pages_slice:
                            if stop_event is not None and stop_event.is_set():
                                break
                            target = _base_path(output_dir, title, ".mp4")
                            if target.exists():
                                print(f"[skip] exists: {target}")
                                done.append(str(target))
                                continue
                            try:
                                page_html = fetch_html(url, page_timeout)
                                embed_url = extract_embed_url(page_html)
                                if not embed_url:
                                    continue
                                result = session.download(
                                    embed_url,
                                    target,
                                    on_progress=progress_callback,
                                    segment_concurrency=segment_concurrency,
                                )
                                if result:
                                    done.append(str(result))
                            except Exception as exc:  # noqa: BLE001 - keep crawling.
                                print(f"[warn] mixi-xxx: {url} failed ({exc})")
                    return done

                files_lock = threading.Lock()
                threads = []
                for offset in range(workers):
                    slice_pages = pages[offset::workers]
                    if not slice_pages:
                        continue
                    threads.append(
                        threading.Thread(
                            target=lambda slice_pages=slice_pages: _extend_files(
                                files, files_lock, process(slice_pages)
                            ),
                            daemon=True,
                        )
                    )
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
            if request.download and files and len(files) < len(pages):
                status = JobStatus.FAILED
                errors.append("download_failed")
            return CrawlResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=status,
                message=f"mixixxx crawl completed: {len(crawl_items)} item(s).",
                items=crawl_items,
                files=files,
                errors=errors,
                metadata={"download": request.download},
            )
        except Exception as exc:  # noqa: BLE001 - adapter normalizes engine failures.
            return CrawlResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=f"mixixxx crawl failed: {exc}",
                errors=["crawl_failed"],
            )

    def _ensure_path(self) -> None:
        lib = str(self.lib_path)
        if lib not in sys.path:
            sys.path.insert(0, lib)


def _extend_files(
    files: list[str], lock: threading.Lock, values: list[str]
) -> None:
    with lock:
        files.extend(values)


def _safe_title(title: str) -> str:
    import re as _re

    safe = _re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .") or "video"
    return _re.sub(r"_+", "_", safe)


def _base_path(output_dir: Path, title: str, suffix: str) -> Path:
    return output_dir / f"{_safe_title(title)}{suffix}"


def _safe_path(output_dir: Path, title: str, suffix: str) -> Path:
    target = _base_path(output_dir, title, suffix)
    if target.exists():
        counter = 1
        while target.exists():
            target = output_dir / f"{_safe_title(title)}_{counter}{suffix}"
            counter += 1
    return target
