"""Compact in-place progress bar UI for CLI jobs.

Layout (width-adaptive):
  ▸[██░░]66%│114/172M│46M/s│2.5s→1.3s│-58M│name
"""

from __future__ import annotations

import math
import os
import shutil
import sys
import threading
from dataclasses import dataclass
from typing import Any, TextIO


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    BLUE = "\033[38;5;33m"
    BLUE_DIM = "\033[38;5;25m"
    CYAN = "\033[38;5;45m"
    SKY = "\033[38;5;75m"
    WHITE = "\033[38;5;255m"
    MUTED = "\033[38;5;245m"
    GREEN = "\033[38;5;40m"


FILL = "█"
EMPTY = "░"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR_LINE = "\033[2K"
CURSOR_UP = "\033[{n}A"
CURSOR_HOME_COL = "\r"


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


def term_columns(fallback: int = 100) -> int:
    try:
        cols = shutil.get_terminal_size((fallback, 24)).columns
    except OSError:
        cols = fallback
    return max(48, cols)


def _strip_ansi(text: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\033":
            i += 1
            if i < len(text) and text[i] == "[":
                i += 1
                while i < len(text) and text[i] not in "mABCDEFGHJKSTf":
                    i += 1
                i += 1
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _visible_len(text: str) -> int:
    return len(_strip_ansi(text))


def _truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return "…"
    return text[: width - 1] + "…"


def _fit_exact(text: str, width: int) -> str:
    """Pad / truncate to exactly `width` visible columns (prevents wrap)."""
    plain = _strip_ansi(text)
    if len(plain) > width:
        out: list[str] = []
        visible = 0
        i = 0
        while i < len(text) and visible < width:
            if text[i] == "\033":
                j = i + 1
                if j < len(text) and text[j] == "[":
                    j += 1
                    while j < len(text) and text[j] not in "mABCDEFGHJKSTf":
                        j += 1
                    j += 1
                    out.append(text[i:j])
                    i = j
                    continue
            if visible == width - 1 and i < len(text) - 1:
                out.append("…")
                visible += 1
                break
            out.append(text[i])
            visible += 1
            i += 1
        return "".join(out) + C.RESET
    return text + (" " * (width - len(plain)))


def fmt_size(n: float) -> str:
    """Short units: 0B 1.2K 45.8M 1.1G"""
    n = max(0.0, float(n))
    for unit, div in (("G", 1024**3), ("M", 1024**2), ("K", 1024), ("B", 1)):
        if n >= div or unit == "B":
            v = n / div
            if unit == "B":
                return f"{int(v)}B"
            if v >= 100:
                return f"{v:.0f}{unit}"
            return f"{v:.1f}{unit}"
    return "0B"


def fmt_size_fixed(n: float, width: int = 5) -> str:
    return fmt_size(n).rjust(width)[:width]


def fmt_pair(current: float, total: float, width: int = 9) -> str:
    """Share unit: 114/172M."""
    total = max(0.0, total)
    current = max(0.0, current)
    for unit, div in (("G", 1024**3), ("M", 1024**2), ("K", 1024), ("B", 1)):
        if total >= div or unit == "B":
            c = current / div
            t = total / div if total else 0.0
            if unit == "B":
                body = f"{int(c)}/{int(t)}B"
            elif t >= 100:
                body = f"{c:.0f}/{t:.0f}{unit}"
            elif t >= 10:
                body = f"{c:.0f}/{t:.0f}{unit}"
            else:
                body = f"{c:.1f}/{t:.1f}{unit}"
            return body.rjust(width)[:width]
    return "?".rjust(width)


def fmt_speed_fixed(n: float, unit: str, width: int = 6) -> str:
    if unit == "bytes":
        body = f"{fmt_size(n)}/s"
    else:
        body = f"{n:.1f}/s"
    return body.rjust(width)[:width]


def fmt_duration_fixed(seconds: float | None, width: int = 5) -> str:
    if seconds is None or not math.isfinite(seconds):
        body = "—"
    else:
        seconds = max(0.0, seconds)
        if seconds < 1:
            body = f"{int(seconds * 1000)}ms"
        elif seconds < 60:
            body = f"{seconds:.1f}s"
        else:
            m, s = divmod(int(seconds), 60)
            if m < 60:
                body = f"{m}m{s:02d}s"
            else:
                h, m = divmod(m, 60)
                body = f"{h}h{m:02d}m"
    return body.rjust(width)[:width]


def fmt_span(elapsed: float, eta: float | None, width: int = 11) -> str:
    """Elapsed→ETA in one slot: 2.5s→1.3s"""
    left = fmt_duration_fixed(elapsed, 5).strip()
    right = fmt_duration_fixed(eta, 5).strip() if eta is not None else "—"
    body = f"{left}→{right}"
    return body.rjust(width)[:width]


def fmt_count_pair(current: float, total: float, width: int = 9) -> str:
    body = f"{int(current)}/{int(total)}"
    return body.rjust(width)[:width]


@dataclass
class ProgressSnapshot:
    current: float
    total: float
    elapsed: float
    label: str = ""
    unit: str = "bytes"
    done: bool = False
    ok: bool = True


@dataclass
class _Layout:
    columns: int
    bar_width: int
    show_speed: bool
    show_span: bool
    show_remaining: bool


def plan_layout(columns: int) -> _Layout:
    cols = max(40, columns)
    if cols >= 100:
        return _Layout(cols, 14, True, True, True)
    if cols >= 80:
        return _Layout(cols, 12, True, True, True)
    if cols >= 64:
        return _Layout(cols, 10, True, True, False)
    return _Layout(cols, 8, True, False, False)


def render_line(snap: ProgressSnapshot, columns: int | None = None) -> str:
    cols = columns if columns is not None else term_columns()
    cols = max(40, cols - 1)
    layout = plan_layout(cols + 1)

    total = max(0.0, snap.total)
    current = min(max(0.0, snap.current), total if total else snap.current)
    if snap.done and snap.ok and total:
        current = total
    ratio = (current / total) if total > 0 else (1.0 if snap.done else 0.0)
    pct = ratio * 100.0

    filled = int(round(ratio * layout.bar_width))
    filled = min(layout.bar_width, max(0, filled))
    bar = f"{C.BLUE}{FILL * filled}{C.BLUE_DIM}{EMPTY * (layout.bar_width - filled)}{C.RESET}"

    elapsed = max(0.0, snap.elapsed)
    speed = current / elapsed if elapsed >= 0.05 else 0.0
    remaining = max(0.0, total - current) if total > 0 else 0.0
    eta = (remaining / speed) if speed > 0 and not snap.done else (0.0 if snap.done else None)

    if snap.done and snap.ok:
        mark = f"{C.GREEN}{C.BOLD}✓{C.RESET}"
    elif snap.done:
        mark = f"{C.MUTED}✗{C.RESET}"
    else:
        mark = f"{C.BOLD}{C.SKY}▸{C.RESET}"

    if snap.unit == "bytes":
        pair = fmt_pair(current, total, 9)
        rem = ("-" + fmt_size(remaining)).rjust(6)[:6]
    else:
        pair = fmt_count_pair(current, total, 9)
        rem = ("-" + str(int(remaining))).rjust(6)[:6]

    sep = f"{C.MUTED}│{C.RESET}"
    parts = [
        mark,
        f"[{bar}]",
        f"{C.CYAN}{C.BOLD}{pct:4.0f}%{C.RESET}",
        sep,
        f"{C.WHITE}{pair}{C.RESET}",
    ]
    if layout.show_speed:
        parts += [sep, f"{C.BLUE}{fmt_speed_fixed(speed, snap.unit, 7)}{C.RESET}"]
    if layout.show_span:
        parts += [sep, f"{C.SKY}{fmt_span(elapsed, eta, 11)}{C.RESET}"]
    if layout.show_remaining:
        parts += [sep, f"{C.WHITE}{rem}{C.RESET}"]

    line = "".join(parts)
    label = snap.label.strip()
    if label:
        used = _visible_len(line) + 1
        room = cols - used
        if room >= 4:
            line += sep + f"{C.DIM}{_truncate(label, room)}{C.RESET}"

    return _fit_exact(line, cols)


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
        state.get("current_file")
        or state.get("label")
        or state.get("state")
        or ""
    )
    return ProgressSnapshot(
        current=current,
        total=total,
        elapsed=float(state.get("elapsed", elapsed) or elapsed),
        label=resolved_label,
        unit=unit,
        done=done or str(state.get("state", "")).lower()
        in {"success", "failed", "cancelled", "complete", "completed"},
        ok=ok,
    )


@dataclass
class LiveTask:
    key: str
    snap: ProgressSnapshot
    finished: bool = False


class LivePanel:
    """Overwrite a fixed block of lines without scrolling the terminal."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdout
        self._tasks: dict[str, LiveTask] = {}
        self._order: list[str] = []
        self._drawn_rows = 0
        self._lock = threading.Lock()
        self._active = False

    def update(self, key: str, snap: ProgressSnapshot) -> None:
        with self._lock:
            if key not in self._tasks:
                self._order.append(key)
                self._tasks[key] = LiveTask(key=key, snap=snap)
            else:
                self._tasks[key].snap = snap
            self._paint_locked()

    def finish(self, key: str, snap: ProgressSnapshot, ok: bool = True) -> None:
        snap = ProgressSnapshot(
            current=snap.total if ok and snap.total else snap.current,
            total=snap.total,
            elapsed=snap.elapsed,
            label=snap.label,
            unit=snap.unit,
            done=True,
            ok=ok,
        )
        with self._lock:
            if key not in self._tasks:
                self._order.append(key)
            self._tasks[key] = LiveTask(key=key, snap=snap, finished=True)
            self._paint_locked()

    def start(self) -> None:
        with self._lock:
            if not self._active:
                self.stream.write(HIDE_CURSOR)
                self.stream.flush()
                self._active = True

    def close(self) -> None:
        with self._lock:
            self._paint_locked()
            if self._active:
                self.stream.write(SHOW_CURSOR)
                self.stream.flush()
                self._active = False

    def clear(self) -> None:
        with self._lock:
            self._tasks.clear()
            self._order.clear()
            if self._drawn_rows:
                self.stream.write(CURSOR_UP.format(n=self._drawn_rows))
                for _ in range(self._drawn_rows):
                    self.stream.write(CURSOR_HOME_COL + CLEAR_LINE + "\n")
                self.stream.write(CURSOR_UP.format(n=self._drawn_rows))
                self.stream.flush()
                self._drawn_rows = 0

    def _paint_locked(self) -> None:
        cols = term_columns()
        lines = [
            render_line(self._tasks[key].snap, columns=cols)
            for key in self._order
            if key in self._tasks
        ]
        if not lines:
            return

        if not self._active:
            self.stream.write(HIDE_CURSOR)
            self._active = True

        if self._drawn_rows:
            self.stream.write(CURSOR_UP.format(n=self._drawn_rows))

        for line in lines:
            self.stream.write(CURSOR_HOME_COL + CLEAR_LINE + line + "\n")

        if self._drawn_rows > len(lines):
            extra = self._drawn_rows - len(lines)
            for _ in range(extra):
                self.stream.write(CURSOR_HOME_COL + CLEAR_LINE + "\n")
            self.stream.write(CURSOR_UP.format(n=extra))

        self.stream.flush()
        self._drawn_rows = len(lines)


def is_interactive_tty(stream: TextIO | None = None) -> bool:
    target = stream or sys.stdout
    return bool(getattr(target, "isatty", lambda: False)())
