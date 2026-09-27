from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from ...engine import IDownloader
from ...models import DownloadRequest, DownloadResult, EngineCapability, JobStatus
from ...net import curl_download
from ...pathing import unique_path

API_BASE = "https://prod.linksvc.xyz"


class LinkexApiError(RuntimeError):
    pass


class LinkexEngine(IDownloader):
    engine_id = "linkex"
    display_name = "Linkex Engine"
    capabilities = EngineCapability(download=True, crawl=False, ranking=False)

    def detect(self, url: str) -> bool:
        host = (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower()
        return host == "l2e.click" or host.endswith(".l2e.click")

    def download(self, request: DownloadRequest) -> DownloadResult:
        try:
            token = _share_token(request.url)
            files = self._resolve(token, Path(request.output_dir), request)
            return DownloadResult(
                job_id=request.job_id,
                engine_id=self.engine_id,
                status=JobStatus.SUCCESS if files else JobStatus.FAILED,
                message=f"Linkex download completed: {len(files)} file(s)." if files else "Linkex files not found.",
                files=files,
                errors=[] if files else ["not_found"],
            )
        except LinkexApiError as exc:
            code = str(exc)
            mapped = "not_found" if "not found" in code.lower() else "network_error"
            return DownloadResult(request.job_id, self.engine_id, JobStatus.FAILED, code, errors=[mapped])
        except Exception as exc:  # noqa: BLE001
            return DownloadResult(request.job_id, self.engine_id, JobStatus.FAILED, str(exc), errors=["download_failed"])

    def _resolve(self, token: str, output: Path, request: DownloadRequest) -> list[str]:
        _api("/api/drive/v1/share/get", {"share_token": token})
        files: list[str] = []
        queue: list[tuple[str | None, tuple[str, ...]]] = [(None, ())]
        while queue:
            parent, folders = queue.pop(0)
            params = {"share_token": token, "page": 1, "page_size": 100, "need_parents": "true"}
            if parent:
                params["parent_id"] = parent
            data = _api("/api/drive/v1/share/get/content", params)
            for item in (data.get("list") or []):
                name = _safe_name(str(item.get("name") or item.get("id") or "file"))
                kind = str(item.get("type") or "").lower()
                if kind in {"dir", "directory", "folder"}:
                    queue.append((str(item.get("id")), folders + (name,)))
                    continue
                media = str(item.get("url") or item.get("download_url") or "").strip()
                if not media:
                    continue
                dest = output.joinpath(*folders, name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest = unique_path(dest)
                curl_download(media, dest, read_timeout_seconds=180)
                files.append(str(dest))
        return files


def _api(path: str, params: dict[str, object]) -> dict:
    key = os.environ.get("LINKEX_API_KEY")
    if not key:
        raise LinkexApiError("configuration_missing: LINKEX_API_KEY")
    query = urlencode(params)
    full_path = f"{path}?{query}" if query else path
    ts = str(int(time.time()))
    headers = {"Content-Type": "application/json", "X-LinkInflu-App": "linkex", "X-LinkInflu-App-Lang": "ja", "X-LinkInflu-Ts": ts}
    header_hash = hashlib.md5("&".join(f"{k.lower()}={v}" for k, v in sorted(headers.items())).encode()).hexdigest()
    headers["X-LinkInflu-Sign"] = hashlib.md5(f"path={full_path}&header={header_hash}&body=&key={key}".encode()).hexdigest()
    try:
        with urlopen(Request(API_BASE + full_path, headers=headers), timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        raise LinkexApiError(f"network_error: {exc}") from exc
    if not isinstance(payload, dict):
        raise LinkexApiError("network_error")
    if int(payload.get("code") or 0) != 0:
        raise LinkexApiError(str(payload.get("message") or "Linkex API failed"))
    return payload.get("data") or {}


def _share_token(url: str) -> str:
    path = urlparse(url if "://" in url else f"https://{url}").path.strip("/")
    match = re.fullmatch(r"i/([^/]+)", path)
    if not match:
        raise LinkexApiError("invalid_request")
    return match.group(1)


def _safe_name(value: str) -> str:
    return (re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")[:160] or "file")
