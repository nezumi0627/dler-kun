from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

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

# gofile.run and mvfile.com share the same "fun800" land-page backend
# (rwzugqnp.fun800.click/app-api). The platform API client and HLS downloader
# live under engines/mvfile; this engine reuses them and adds gofile.run
# detection plus recursive channel listing.
from ..mvfile import api as fun800_api
from ..mvfile.hls import (
    MvfileDownloadError,
    download_hls_to_mp4,
    sanitize_filename,
    target_mp4_path,
)


@dataclass(frozen=True)
class MediaTarget:
    entry: fun800_api.MvfileEntry
    rel_dir: tuple[str, ...] = ()
    filename: str = ""

    @property
    def name(self) -> str:
        return self.filename or target_mp4_path(Path(), self.entry.name).name

    @property
    def media_url(self) -> str | None:
        return self.entry.media_url

    def target_path(self, output_dir: Path) -> Path:
        folder = Path(*self.rel_dir) if self.rel_dir else Path()
        return output_dir / folder / self.name


class GofileRunEngine(IDownloader):
    engine_id = "gofilerun"
    display_name = "GoFile.run Engine"
    capabilities = EngineCapability(download=True, crawl=True, ranking=False)

    def detect(self, url: str) -> bool:
        host = (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower()
        return host == "gofile.run" or host.endswith(".gofile.run")

    def download(self, request: DownloadRequest) -> DownloadResult:
        try:
            api_base = str(request.options.get("api_base") or fun800_api.DEFAULT_API_BASE)
            timeout_seconds = float(request.options.get("timeout_seconds", 30.0))
            force = bool(request.options.get("force", False))
            local_addr = str(request.options.get("local_addr") or "")
            proxy = str(request.options.get("proxy") or "")
            password = request.options.get("password")
            targets = collect_media(
                request.url,
                api_base=api_base,
                timeout_seconds=timeout_seconds,
                password=str(password) if password else None,
            )
            if not targets:
                return DownloadResult(
                    job_id=request.job_id,
                    engine_id=self.engine_id,
                    status=JobStatus.FAILED,
                    message="GoFile.run media not found.",
                    errors=["not_found"],
                )
            output_dir = Path(request.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            files: list[str] = []
            errors: list[str] = []
            progress = request.options.get("progress_callback")
            total = len(targets)
            for index, target in enumerate(targets, start=1):
                if callable(progress):
                    progress(
                        {
                            "completed_files": index - 1,
                            "total_files": total,
                            "current_file": target.name,
                            "state": "downloading",
                        }
                    )
                if not target.media_url:
                    errors.append("not_found")
                    continue
                try:
                    path = download_hls_to_mp4(
                        target.media_url,
                        target.target_path(output_dir),
                        referer=target.entry.page_url,
                        force=force,
                        timeout_seconds=timeout_seconds,
                        local_addr=local_addr,
                        proxy=proxy,
                    )
                    files.append(str(path))
                except MvfileDownloadError as exc:
                    message = str(exc)
                    if message.startswith("dependency_missing"):
                        return DownloadResult(
                            job_id=request.job_id,
                            engine_id=self.engine_id,
                            status=JobStatus.FAILED,
                            message=message,
                            errors=["dependency_missing"],
                            files=files,
                        )
                    errors.append(message)
                except OSError as exc:
                    errors.append(str(exc))
            if callable(progress):
                progress(
                    {
                        "completed_files": len(files),
                        "total_files": total,
                        "progress": (
                            100
                            if not errors
                            else round((len(files) / total) * 100, 2)
                        ),
                        "state": "downloading",
                    }
                )
            status = JobStatus.SUCCESS if files and not errors else JobStatus.FAILED
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=status,
                message=(
                    f"GoFile.run download completed: {len(files)}/{total} file(s)."
                    if files
                    else "GoFile.run download failed."
                ),
                files=files,
                errors=(["download_failed"] if errors else []),
                metadata={
                    "failed": errors[:20],
                    "items": [
                        {
                            "short_link": target.entry.short_link,
                            "name": target.name,
                            "folder": "/".join(target.rel_dir),
                            "page_url": target.entry.page_url,
                            "media_url": target.media_url,
                        }
                        for target in targets
                    ],
                },
            )
        except fun800_api.MvfileApiError as exc:
            return self._api_error_result(request.job_id, str(exc))
        except Exception as exc:  # noqa: BLE001 - adapter normalizes failures.
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=str(exc),
                errors=["download_failed"],
            )

    def crawl(self, request: CrawlRequest) -> CrawlResult:
        try:
            seeds = [str(seed) for seed in (request.seeds or []) if str(seed).strip()]
            if not seeds and request.options.get("seed"):
                seeds = [str(request.options["seed"])]
            if not seeds:
                return CrawlResult(
                    job_id=request.job_id,
                    engine_id=self.engine_id,
                    status=JobStatus.FAILED,
                    message="GoFile.run crawl requires a seed URL.",
                    errors=["invalid_request"],
                )
            api_base = str(request.options.get("api_base") or fun800_api.DEFAULT_API_BASE)
            timeout_seconds = float(request.options.get("timeout_seconds", 30.0))
            password = request.options.get("password")
            local_addr = str(request.options.get("local_addr") or "")
            proxy = str(request.options.get("proxy") or "")
            media_entries: list[MediaTarget] = []
            for seed in seeds:
                media_entries.extend(
                    collect_media(
                        seed,
                        api_base=api_base,
                        timeout_seconds=timeout_seconds,
                        password=str(password) if password else None,
                    )
                )
            items = [self._to_crawl_item(entry) for entry in media_entries]
            files: list[str] = []
            errors: list[str] = []
            if request.download and media_entries:
                output_dir = Path(request.output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                force = bool(
                    request.options.get("force") or request.options.get("overwrite")
                )
                progress = request.options.get("progress_callback")
                total = len(media_entries)
                for index, target in enumerate(media_entries, start=1):
                    if callable(progress):
                        progress(
                            {
                                "completed_files": index - 1,
                                "total_files": total,
                                "current_file": target.name,
                                "state": "downloading",
                            }
                        )
                    if not target.media_url:
                        errors.append("not_found")
                        continue
                    try:
                        path = download_hls_to_mp4(
                            target.media_url,
                            target.target_path(output_dir),
                            referer=target.entry.page_url,
                            force=force,
                            timeout_seconds=timeout_seconds,
                            local_addr=local_addr,
                            proxy=proxy,
                        )
                        files.append(str(path))
                    except MvfileDownloadError as exc:
                        if str(exc).startswith("dependency_missing"):
                            return CrawlResult(
                                job_id=request.job_id,
                                engine_id=self.engine_id,
                                status=JobStatus.FAILED,
                                message=str(exc),
                                items=items,
                                files=files,
                                errors=["dependency_missing"],
                            )
                        errors.append(str(exc))
            status = JobStatus.SUCCESS
            if request.download and media_entries and len(files) < len(media_entries):
                status = JobStatus.FAILED
                if "download_failed" not in errors:
                    errors.append("download_failed")
            return CrawlResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=status,
                message=f"GoFile.run crawl completed: {len(items)} item(s).",
                items=items,
                files=files,
                errors=errors if status == JobStatus.FAILED else [],
                metadata={"download": request.download},
            )
        except fun800_api.MvfileApiError as exc:
            code = str(exc)
            mapped = (
                code
                if code
                in {
                    "auth_required",
                    "not_found",
                    "invalid_request",
                    "network_error",
                }
                or code.startswith("network_error")
                else "crawl_failed"
            )
            if mapped.startswith("network_error"):
                mapped = "network_error"
            return CrawlResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=str(exc),
                errors=[mapped],
            )
        except Exception as exc:  # noqa: BLE001
            return CrawlResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.FAILED,
                message=str(exc),
                errors=["crawl_failed"],
            )

    def get_metadata(self, url: str) -> dict:
        try:
            short_link = fun800_api.extract_short_link(url)
            if not short_link:
                return {"url": url, "engine_id": self.engine_id}
            domain = fun800_api.page_domain_from_url(url)
            entry = fun800_api.fetch_info(
                short_link,
                domain=domain,
                api_base=fun800_api.DEFAULT_API_BASE,
            )
            return {
                "url": url,
                "engine_id": self.engine_id,
                "name": entry.name,
                "is_folder": entry.is_folder,
                "file_size": entry.file_size,
                "duration": entry.duration,
                "thumbnail_url": entry.thumbnail_url,
                "media_url": entry.media_url,
                "channel_link": entry.channel_link,
            }
        except Exception:  # noqa: BLE001 - metadata is best-effort.
            return {"url": url, "engine_id": self.engine_id}

    @staticmethod
    def _to_crawl_item(target: MediaTarget) -> CrawlItem:
        entry = target.entry
        return CrawlItem(
            url=entry.page_url,
            title=entry.name,
            thumbnail_url=entry.thumbnail_url,
            size=entry.file_size,
            duration=entry.duration,
            downloadable=True,
            metadata={
                "short_link": entry.short_link,
                "media_url": entry.media_url,
                "channel_link": entry.channel_link,
                "folder": "/".join(target.rel_dir),
            },
        )

    def _api_error_result(self, job_id: str, code: str) -> DownloadResult:
        mapped = code
        if code.startswith("network_error"):
            mapped = "network_error"
        if mapped not in {
            "unsupported_service",
            "invalid_request",
            "not_found",
            "auth_required",
            "network_error",
            "download_failed",
            "dependency_missing",
        }:
            mapped = "download_failed"
        return DownloadResult(
            job_id=job_id,
            engine_id=self.engine_id,
            status=JobStatus.FAILED,
            message=code,
            errors=[mapped],
        )


def collect_media(
    url: str,
    *,
    api_base: str = fun800_api.DEFAULT_API_BASE,
    timeout_seconds: float = 30.0,
    password: str | None = None,
) -> list[MediaTarget]:
    """Resolve every media file reachable from a gofile.run landing page.

    A single-file page links back to its channel folder via extraInfo; the
    channel is listed recursively so nested folders are fully expanded.
    Each target carries the folder path (relative to the output root) that
    mirrors the channel hierarchy.
    """
    short_link = fun800_api.extract_short_link(url)
    if not short_link:
        raise fun800_api.MvfileApiError("invalid_request")
    domain = fun800_api.page_domain_from_url(url)
    root = fun800_api.fetch_info(
        short_link,
        domain=domain,
        api_base=api_base,
        timeout_seconds=timeout_seconds,
        password=password,
    )
    if root.is_folder:
        start: tuple[fun800_api.MvfileEntry, tuple[str, ...]] = (root, ())
    elif root.channel_link:
        channel = fun800_api.fetch_info(
            root.channel_link,
            domain=domain,
            api_base=api_base,
            timeout_seconds=timeout_seconds,
            password=password,
        )
        start = (channel, ())
    else:
        return [MediaTarget(entry=root)] if root.media_url else []

    media: list[MediaTarget] = []
    seen: set[str] = set()
    queue: list[tuple[fun800_api.MvfileEntry, tuple[str, ...]]] = [start]
    while queue:
        node, rel_dir = queue.pop(0)
        if not node.short_link or node.short_link in seen:
            continue
        seen.add(node.short_link)
        if node.is_folder:
            child_dir = rel_dir + (sanitize_filename(node.name),)
            for child in fun800_api.list_entries(
                node.short_link,
                domain=domain,
                api_base=api_base,
                timeout_seconds=timeout_seconds,
            ):
                queue.append((child, child_dir))
            continue
        detail = node
        if not detail.media_url:
            detail = fun800_api.fetch_info(
                node.short_link,
                domain=domain,
                api_base=api_base,
                timeout_seconds=timeout_seconds,
                password=password,
            )
        if detail.media_url:
            media.append(MediaTarget(entry=detail, rel_dir=rel_dir))
    return _dedupe_targets(media)


def _dedupe_targets(targets: list[MediaTarget]) -> list[MediaTarget]:
    """Disambiguate colliding filenames so every distinct video is kept.

    The platform sometimes exposes different files under the same display
    name; appending " (2)" (and up) keeps both while preserving the first.
    """
    used: dict[tuple[str, ...], set[str]] = {}
    result: list[MediaTarget] = []
    for target in targets:
        base = target_mp4_path(Path(), target.entry.name).name
        collided = used.setdefault(target.rel_dir, set())
        filename = base
        counter = 2
        while filename in collided:
            stem, ext = os.path.splitext(base)
            filename = f"{stem} ({counter}){ext}"
            counter += 1
        collided.add(filename)
        result.append(MediaTarget(entry=target.entry, rel_dir=target.rel_dir, filename=filename))
    return result
