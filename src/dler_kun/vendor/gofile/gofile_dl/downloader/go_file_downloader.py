# go_file_downloader.py

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from ..token.token_manager import TokenManager
from .file_downloader import FileDownloader, _make_progress
from .go_file_api import GoFileAPI

console = Console()


class GoFileDownloader:
    """GoFile.io のコンテンツをダウンロードするメインクラス"""

    MAX_DL = 20
    MAX_API = 5

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: Optional[str] = None,
        proxy: Optional[str] = None,
        local_addr: Optional[str] = None,
    ):
        self.session = session
        self.token = token
        self.proxy = proxy
        self.local_addr = local_addr
        self._api: Optional[GoFileAPI] = None
        self._downloader: Optional[FileDownloader] = None
        self._token_manager = None

    async def init(self):
        if not self.token:
            self._token_manager = TokenManager()
            self.token = await self._token_manager.get_or_create_token()
        self._api = GoFileAPI(
            self.session,
            self.token,
            proxy=self.proxy,
            local_addr=self.local_addr,
        )
        self._downloader = FileDownloader(
            self.session,
            self.token,
            max_concurrent_requests=self.MAX_DL,
            proxy=self.proxy,
            local_addr=self.local_addr,
        )

    def _normalize_url(self, url_or_id: str) -> str:
        if url_or_id.startswith(("http://", "https://")):
            m = re.search(r"gofile\.io/d/([a-zA-Z0-9]+)", url_or_id)
            if m:
                return m.group(1)
        if re.match(r"^[a-zA-Z0-9]+$", url_or_id):
            return url_or_id
        return f"Invalid URL or ID format: {url_or_id}"

    async def _extract_files(
        self,
        content_data: Dict[str, Any],
        parent_path: str = "",
    ) -> List[Dict[str, Any]]:
        if content_data["type"] == "file":
            return [
                {
                    "name": os.path.join(parent_path, content_data["name"]),
                    "link": content_data["link"],
                    "size": content_data.get("size"),
                }
            ]

        files: List[Dict[str, Any]] = []
        folder_path = os.path.join(parent_path, content_data["name"])
        children = content_data.get("children", {})

        for child in children.values():
            if child["type"] != "folder":
                files.append(
                    {
                        "name": os.path.join(folder_path, child["name"]),
                        "link": child["link"],
                        "size": child.get("size"),
                    }
                )

        sub_folders = [c for c in children.values() if c["type"] == "folder"]
        if sub_folders:
            sem = asyncio.Semaphore(self.MAX_API)

            async def _fetch_sub(child):
                async with sem:
                    data = await self._api.fetch_content(child["id"])
                    return await self._extract_files(data, folder_path) if data else []

            results = await asyncio.gather(
                *(_fetch_sub(c) for c in sub_folders),
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, list):
                    files.extend(r)

        return files

    async def download(
        self,
        url_or_id: str,
        password: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": "success",
            "message": "",
            "files": [],
            "errors": [],
        }

        try:
            content_id = self._normalize_url(url_or_id)
            if "Invalid URL or ID format" in content_id:
                result["status"] = "error"
                result["message"] = content_id
                return result

            output_path = Path(output_dir) if output_dir else Path("./downloads")
            content_id_dir = output_path / content_id
            content_id_dir.mkdir(parents=True, exist_ok=True)

            # ── コンテンツ情報取得 ──────────────────────────────────────────
            console.print(
                f"  [dim]Fetching[/] [yellow]{content_id}[/] ...",
                highlight=False,
            )
            try:
                content_data = await self._api.fetch_content(content_id, password)
            except FileNotFoundError as e:
                result["status"] = "not_found"
                result["message"] = str(e)
                return result
            except ValueError as e:
                # 接続エラーやレート制限などのエラーが起きた場合はスキップする
                result["status"] = "error"
                result["message"] = str(e)
                return result
            except Exception as e:
                result["status"] = "error"
                result["message"] = f"予期せぬエラー: {e}"
                return result
            if not content_data:
                result["status"] = "error"
                result["message"] = "Failed to fetch content data"
                return result

            files_to_download = await self._extract_files(content_data)
            total = len(files_to_download)
            total_bytes = sum(f.get("size") or 0 for f in files_to_download)

            # ── Progress UI ────────────────────────────────────────────────
            # 全体バー
            overall = Progress(
                TextColumn("[bold white] Overall"),
                BarColumn(bar_width=34, complete_style="bright_cyan"),
                MofNCompleteColumn(),
                TextColumn("[dim]{task.fields[speed]:>12}"),
                TimeElapsedColumn(),
                TextColumn("[dim]ETA"),
                TimeRemainingColumn(),
                console=console,
                expand=False,
            )
            overall_task: TaskID = overall.add_task("Overall", total=total, speed="")

            # ファイルバー（常に最大 12 行を固定表示、古い行は消える）
            file_progress = _make_progress()
            self._downloader._progress = file_progress

            def _layout() -> Table:
                grid = Table.grid(padding=0)
                grid.add_row(
                    Panel(
                        overall,
                        title="[bold magenta]GoFile Downloader",
                        border_style="bright_blue",
                        padding=(0, 1),
                    )
                )
                grid.add_row(
                    Panel(
                        file_progress,
                        title="[bold cyan]Active Downloads  [dim](last 12)[/]",
                        border_style="blue",
                        padding=(0, 1),
                    )
                )
                return grid

            t0 = time.monotonic()
            done = 0
            sem = asyncio.Semaphore(self.MAX_DL)

            async def _dl(file_info):
                nonlocal done
                async with sem:
                    dest = content_id_dir / file_info["name"]
                    res = await self._downloader.download_file(
                        file_info["link"],
                        dest,
                        expected_size=file_info.get("size") or 0,
                    )
                done += 1
                elapsed = max(time.monotonic() - t0, 1e-6)
                # 完了バイト数を概算（スキップ含む）
                done_bytes = sum(
                    files_to_download[i].get("size") or 0
                    for i in range(min(done, total))
                )
                speed_mb = done_bytes / elapsed / 1024 / 1024
                overall.update(
                    overall_task,
                    advance=1,
                    speed=f"{speed_mb:6.1f} MB/s",
                )
                return res

            with Live(
                _layout(),
                console=console,
                refresh_per_second=12,
                vertical_overflow="crop",  # ← ターミナル高さを超えたらクロップ
            ) as live:
                live.update(_layout())
                download_results = await asyncio.gather(
                    *(_dl(fi) for fi in files_to_download),
                    return_exceptions=True,
                )

            # ── 集計 ───────────────────────────────────────────────────────
            elapsed = time.monotonic() - t0
            speed = total_bytes / elapsed / 1024 / 1024 if elapsed > 0 else 0
            ok = 0

            for fi, res in zip(files_to_download, download_results):
                err = str(res) if isinstance(res, Exception) else None
                result["files"].append(
                    {
                        "filename": fi["name"],
                        "path": str(content_id_dir / fi["name"]),
                        "size": fi.get("size"),
                        "success": err is None,
                    }
                )
                if err:
                    result["errors"].append(err)
                else:
                    ok += 1

            # ── サマリー ───────────────────────────────────────────────────
            if result["errors"]:
                result["status"] = "partial"
                msg = f"{ok}/{total} files  {elapsed:.1f}s  ~{speed:.1f} MB/s"
                result["message"] = msg
                err_lines = "\n".join(f"  [red]✗[/] {e}" for e in result["errors"][:5])
                console.print(
                    Panel(
                        f"[yellow]⚠  {msg}[/]\n{err_lines}",
                        title="[yellow]Partial",
                        border_style="yellow",
                    )
                )
            else:
                msg = f"{ok} files  {elapsed:.1f}s  ~{speed:.1f} MB/s"
                result["message"] = msg
                console.print(
                    Panel(
                        f"[bold green]✔  {msg}[/]",
                        title="[green]Done",
                        border_style="green",
                    )
                )

        except Exception as e:
            result["status"] = "error"
            result["message"] = f"Error: {e}"
            result["errors"].append(str(e))
            console.print_exception()

        return result
