import asyncio
import os
from collections import deque
from pathlib import Path
from typing import Optional

import aiohttp
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TransferSpeedColumn,
)

console = Console()


def _get_proxy() -> Optional[str]:
    return os.environ.get("GOFILE_PROXY") or None


def _make_progress() -> Progress:
    """個別ファイル用の Progress を生成する。"""
    return Progress(
        SpinnerColumn(spinner_name="dots"),
        TextColumn("[bold cyan]{task.description:<38}[/]"),
        BarColumn(bar_width=26, complete_style="green", finished_style="bright_green"),
        "[progress.percentage]{task.percentage:>3.0f}%",
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeElapsedColumn(),
        expand=False,
        console=console,
    )


# 同時表示する最大ファイル行数
_MAX_VISIBLE = 12


class FileDownloader:
    """GoFile.io からファイルをダウンロードするクラス"""

    CHUNK_SIZE = 2 * 1024 * 1024
    READ_BUFSIZE = 2 * 1024 * 1024
    MAX_CONCURRENT = 20

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str,
        chunk_size: int = CHUNK_SIZE,
        max_concurrent_requests: int = MAX_CONCURRENT,
        proxy: Optional[str] = None,
        local_addr: Optional[str] = None,
    ):
        self.session = session
        self.token = token
        self._chunk_size = chunk_size
        self._max_concurrent_requests = max_concurrent_requests
        self._proxy: Optional[str] = proxy or _get_proxy()
        self._local_addr: Optional[str] = (
            local_addr or os.environ.get("GOFILE_LOCAL_ADDR") or None
        )
        # go_file_downloader から注入される共有 Progress
        self._progress: Optional[Progress] = None
        # 表示中の task id キュー（最大 _MAX_VISIBLE 件）
        self._visible_tasks: deque = deque()
        self._visible_lock = asyncio.Lock()

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    async def _add_task(self, description: str, total: Optional[int]) -> TaskID:
        """Progress に task を追加し、古いものを非表示にする。"""
        assert self._progress is not None
        async with self._visible_lock:
            tid = self._progress.add_task(description, total=total)
            self._visible_tasks.append(tid)
            # 超過分を非表示（completed 扱い）
            while len(self._visible_tasks) > _MAX_VISIBLE:
                old = self._visible_tasks.popleft()
                self._progress.update(old, visible=False)
        return tid

    async def download_file(
        self,
        url: str,
        file_path: Path,
        expected_size: int = 0,
    ) -> bool:
        """ダウンロードして file_path に保存。成功すると True を返す。"""
        tmp_file = Path(str(file_path) + ".part")
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # ── DL済み判定 ─────────────────────────────────────────────────────
        if file_path.exists():
            if file_path.stat().st_size > 0:
                # スキップ：完了済み（非空）ファイルは再 DL しない
                return True
            file_path.unlink()

        if tmp_file.exists():
            try:
                tmp_file.unlink()
            except OSError:
                pass

        # ── ダウンロード実行 ───────────────────────────────────────────────
        tid: Optional[TaskID] = None
        name = file_path.name

        try:
            async with self.session.get(
                url,
                headers=self._dl_headers(),
                read_bufsize=self.READ_BUFSIZE,
                **self._proxy_kwargs(),
            ) as resp:
                if resp.status != 200:
                    raise ValueError(f"HTTP {resp.status}")

                total = int(resp.headers.get("Content-Length", 0))

                if self._progress:
                    tid = await self._add_task(
                        f"[cyan]{name[:36]}",
                        total=total if total > 0 else None,
                    )

                loop = asyncio.get_running_loop()
                fh = await loop.run_in_executor(None, lambda: open(tmp_file, "wb"))
                downloaded = 0
                try:
                    async for chunk in resp.content.iter_chunked(self._chunk_size):
                        await loop.run_in_executor(None, fh.write, chunk)
                        downloaded += len(chunk)
                        if self._progress and tid is not None:
                            self._progress.update(tid, advance=len(chunk))
                finally:
                    await loop.run_in_executor(None, fh.close)

                if self._progress and tid is not None:
                    self._progress.update(
                        tid,
                        description=f"[green]✓ {name[:36]}",
                        completed=total if total > 0 else downloaded,
                    )

            tmp_file.replace(file_path)
            return True

        except Exception:
            if self._progress and tid is not None:
                self._progress.update(
                    tid,
                    description=f"[red]✗ {name[:36]}",
                )
            try:
                if tmp_file.exists():
                    tmp_file.unlink()
            except OSError:
                pass
            raise

    async def download_files(self, urls: list, file_paths: list) -> bool:
        sem = asyncio.Semaphore(self._max_concurrent_requests)

        async def _one(url, fp):
            async with sem:
                return await self.download_file(url, fp)

        results = await asyncio.gather(
            *(_one(u, p) for u, p in zip(urls, file_paths)),
            return_exceptions=True,
        )
        return all(r is True for r in results)

    def _dl_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/149.0.0.0 Safari/537.36"
            ),
        }

    def _proxy_kwargs(self) -> dict:
        if self._proxy and not self._proxy.startswith("socks"):
            return {"proxy": self._proxy}
        return {}
