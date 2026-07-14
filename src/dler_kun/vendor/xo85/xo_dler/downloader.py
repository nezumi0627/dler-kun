from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

from .crawler import DEFAULT_USER_AGENT
from .models import MediaItem


@dataclass(frozen=True)
class DownloadConfig:
    output_dir: Path = Path("downloads")
    timeout_seconds: float = 60.0
    chunk_size: int = 1024 * 1024
    skip_existing: bool = True
    user_agent: str = DEFAULT_USER_AGENT
    headers: dict[str, str] = field(default_factory=dict)


def download_items(items: list[MediaItem], config: DownloadConfig) -> list[Path]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []

    for item in items:
        target = target_path(config.output_dir, item)
        if target.exists() and config.skip_existing:
            print(f"[skip] exists: {target}")
            downloaded.append(target)
            continue
        if target.exists():
            target = unique_target_path(target)

        if download_file(item, target, config):
            write_metadata(target, item)
            downloaded.append(target)

    return downloaded


def download_file(item: MediaItem, target: Path, config: DownloadConfig) -> bool:
    part_path = target.with_suffix(target.suffix + ".part")
    request = Request(item.url, headers=download_headers(item, config))

    try:
        with urlopen(request, timeout=config.timeout_seconds) as response:
            with part_path.open("wb") as file:
                while True:
                    chunk = response.read(config.chunk_size)
                    if not chunk:
                        break
                    file.write(chunk)
        part_path.replace(target)
        print(f"[done] {target}")
        return True
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        print(f"[warn] download failed: {item.url} ({exc})")
        if part_path.exists():
            part_path.unlink(missing_ok=True)
        return False


def download_headers(item: MediaItem, config: DownloadConfig) -> dict[str, str]:
    headers = {
        "User-Agent": config.user_agent,
        "Accept": "*/*",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        **config.headers,
    }
    if item.source_page:
        headers.setdefault("Referer", item.source_page)
    return headers


def target_path(output_dir: Path, item: MediaItem) -> Path:
    parsed = urlparse(item.url)
    raw_name = filename_from_query(parsed.query) or unquote(Path(parsed.path).name) or item.display_name
    safe_name = sanitize_filename(raw_name)
    if not Path(safe_name).suffix:
        safe_name = f"{safe_name}.bin"

    return output_dir / safe_name


def filename_from_query(query: str) -> str | None:
    values = parse_qs(query)
    if values.get("download_filename"):
        return values["download_filename"][0]
    if values.get("file"):
        return Path(unquote(values["file"][0])).name
    return None


def unique_target_path(target: Path) -> Path:
    base_stem = target.stem
    suffix = target.suffix
    counter = 2
    while target.exists():
        target = target.with_name(f"{base_stem}-{counter}{suffix}")
        counter += 1
    return target


def write_metadata(target: Path, item: MediaItem) -> None:
    metadata_path = target.with_suffix(target.suffix + ".json")
    payload = asdict(item)
    if item.published_at is not None:
        payload["published_at"] = item.published_at.isoformat()
    metadata_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def sanitize_filename(value: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
    return sanitized[:180] or "download"
