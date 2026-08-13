"""Progress UI backed by `rich.progress` (the popular rich look).

Keeps the same small API as the old custom renderer so managers.py is
unchanged: a ``LivePanel`` renders one live progress row per job.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, TextIO

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)


def enable_windows_ansi() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def is_interactive_tty(stream: TextIO | None = None) -> bool:
    target = stream or sys.stdout
    return bool(getattr(target, "isatty", lambda: False)())


@dataclass
class ProgressSnapshot:
    current: float
    total: float
    elapsed: float
    label: str = ""
    unit: str = "bytes"
    done: bool = False
    ok: bool = True


def snapshot_from_state(
    state: dict[str, Any],
    *,
    elapsed: float = 0.0,
    label: str = "",
    done: bool = False,
    ok: bool = True,
) -> ProgressSnapshot:
    """Map engine progress_callback dicts onto ProgressSnapshot."""
    completed_files = state.get("completed_files")
    total_files = state.get("total_files")
    if completed_files is not None and total_files is not None:
        current = float(completed_files)
        total = float(total_files)
        unit = "files"
    elif state.get("bytes_done") is not None and state.get("bytes_total") is not None:
        current = float(state["bytes_done"])
        total = float(state["bytes_total"])
        unit = "bytes"
    else:
        progress = float(state.get("progress", 0) or 0)
        current = max(0.0, min(100.0, progress))
        total = 100.0
        unit = "files"
        eta_raw = str(state.get("eta") or "")
        if "/" in eta_raw:
            left, _, right = eta_raw.partition("/")
            try:
                current = float(left.strip())
                total = float(right.strip())
                unit = "files"
            except ValueError:
                pass

    resolved_label = label or str(
        state.get("current_file") or state.get("label") or state.get("state") or ""
    )
    return ProgressSnapshot(
        current=current,
        total=total,
        elapsed=float(state.get("elapsed", elapsed) or elapsed),
        label=resolved_label,
        unit=unit,
        done=done
        or str(state.get("state", "")).lower()
        in {"success", "failed", "cancelled", "complete", "completed"},
        ok=ok,
    )


class LivePanel:
    """Live progress rows via rich, one per job."""

    def __init__(self, stream: TextIO | None = None) -> None:
        console = Console(file=stream or sys.stdout, highlight=False, no_color=False)
        self._progress = Progress(
            TextColumn("[bold]{task.description}", justify="left"),
            BarColumn(bar_width=14),
            "[progress.percentage]{task.percentage:>3.0f}%",
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=True,
        )
        self._tasks: dict[str, TaskID] = {}

    def start(self) -> None:
        self._progress.start()

    def update(self, key: str, snap: ProgressSnapshot) -> None:
        task_id = self._tasks.get(key)
        if task_id is None:
            task_id = self._progress.add_task(
                snap.label or key,
                total=max(snap.total, 0.0) or None,
            )
            self._tasks[key] = task_id
        self._progress.update(
            task_id,
            total=max(snap.total, 0.0) or None,
            description=snap.label or key,
            completed=min(snap.current, snap.total) if snap.total else snap.current,
        )

    def finish(self, key: str, snap: ProgressSnapshot, ok: bool = True) -> None:
        task_id = self._tasks.get(key)
        if task_id is None:
            task_id = self._progress.add_task(
                snap.label or key,
                total=max(snap.total, 0.0) or None,
            )
            self._tasks[key] = task_id
        self._progress.update(
            task_id,
            description=snap.label or key,
            completed=snap.total if ok and snap.total else snap.current,
        )

    def close(self) -> None:
        try:
            self._progress.stop()
        except Exception:
            pass
