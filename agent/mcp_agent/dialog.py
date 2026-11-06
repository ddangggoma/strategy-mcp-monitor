"""Notice windows: an Edge ``--app`` window (V3, C1), the default browser without Edge (V25), and a
print window that writes OPEN/CLOSE lines for E2E and integration tests (V24)."""

from __future__ import annotations

import os
import subprocess
import threading
import time
import webbrowser
import winreg
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from mcp_agent import win32

# document.title of web/notice.html. Edge --app windows are captioned with it, which is how the
# notice window is told apart from other Edge windows (C1). Keep in step with the notice page.
NOTICE_TITLE = "MCP Monitor"

EDGE_APP_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
EDGE_RELATIVE = os.path.join("Microsoft", "Edge", "Application", "msedge.exe")


class NoticeWindow(Protocol):
    def open(self, url: str, display_id: int) -> None: ...

    def close(self) -> None: ...

    def closed_by_user(self) -> bool:
        """True when the window went away without us closing it."""
        ...


class PrintWindow:
    def __init__(self, url_file: Path) -> None:
        self._file = url_file
        self._open: int | None = None

    def _write(self, line: str) -> None:
        with open(self._file, "a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")

    def open(self, url: str, display_id: int) -> None:
        self._write(f"OPEN {display_id} {url}")
        self._open = display_id

    def close(self) -> None:
        if self._open is not None:
            self._write(f"CLOSE {self._open}")
            self._open = None

    def closed_by_user(self) -> bool:
        return False


def edge_command(edge: str, url: str, profile_dir: Path) -> list[str]:
    return [edge, f"--app={url}", f"--user-data-dir={profile_dir}", "--no-first-run", "--no-default-browser-check",
            "--disable-sync", "--window-size=640,600"]


def _read_app_path(hive: int) -> str | None:
    try:
        with winreg.OpenKey(hive, EDGE_APP_PATH) as key:
            value, _kind = winreg.QueryValueEx(key, "")
    except OSError:
        return None
    return value if isinstance(value, str) else None


def find_edge(*, read_app_path: Callable[[int], str | None] = _read_app_path,
              environ: Mapping[str, str] = os.environ, isfile: Callable[[str], bool] = os.path.isfile) -> str | None:
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        value = (read_app_path(hive) or "").strip().strip('"')
        if value and isfile(value):
            return value
    for var in ("ProgramFiles(x86)", "ProgramFiles"):
        base = environ.get(var)
        if base:
            candidate = os.path.join(base, EDGE_RELATIVE)
            if isfile(candidate):
                return candidate
    return None


def taskkill_tree(pid: int, *, run: Callable[..., Any] = subprocess.run) -> None:
    run(["taskkill", "/PID", str(pid), "/T", "/F"], creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True)


class WindowOps(Protocol):
    """The Win32 side of :class:`EdgeWindow` (faked in tests)."""

    def edge_windows(self) -> dict[int, tuple[int, str]]: ...  # hwnd -> (owner pid, caption), any msedge

    def process_tree(self, pid: int) -> list[int]: ...  # pid, then live descendants, parents first

    def place(self, hwnd: int) -> bool: ...  # centre + HWND_TOPMOST + foreground

    def is_window(self, hwnd: int) -> bool: ...

    def pid_alive(self, pid: int) -> bool: ...


class Win32WindowOps:
    def edge_windows(self) -> dict[int, tuple[int, str]]:
        return win32.edge_windows()

    def process_tree(self, pid: int) -> list[int]:
        return win32.process_tree(pid, image=win32.EDGE_IMAGE)

    def place(self, hwnd: int) -> bool:
        return win32.place_topmost(hwnd)

    def is_window(self, hwnd: int) -> bool:
        return win32.is_window(hwnd)

    def pid_alive(self, pid: int) -> bool:
        return win32.pid_alive(pid)


@dataclass(eq=False)
class _Shown:
    proc: Any  # subprocess.Popen, or a fake with .pid and .poll()
    before: frozenset[int]  # Edge windows that existed before this launch: never adopted
    opened_at: float
    hwnd: int | None = None
    owner: int | None = None
    placed: bool = False
    closed_by_us: bool = False
    stop: threading.Event = field(default_factory=threading.Event)


class EdgeWindow:
    """The notice as an Edge ``--app`` window, kept centred and top-most (V3, C1).

    The msedge.exe we start usually hands over to a browser child and exits at once (seen on this
    PC), and Edge may also hand the URL to an unrelated browser process (F10). So the window is
    looked up among ALL msedge windows created after the launch: a window of the launched process
    tree wins (its caption should be ``title``; any non-empty caption is accepted there, since our
    dedicated profile opens nothing else), otherwise a window captioned ``title`` anywhere.

    "Closed by the user" means that window is gone, never that the launched pid exited. If no
    window was found within ``locate_sec``, it means the launched tree has fully exited.
    """

    def __init__(self, edge: str | None, profile_dir: Path, *, popen: Callable[..., Any] = subprocess.Popen,
                 kill_tree: Callable[[int], None] = taskkill_tree, ops: WindowOps | None = None,
                 title: str = NOTICE_TITLE, locate_sec: float = 5.0, retry_sec: float = 0.2, exit_wait_sec: float = 2.0,
                 monotonic: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 browser_open: Callable[[str], Any] = webbrowser.open) -> None:
        self._edge = edge
        self._profile_dir = profile_dir
        self._popen = popen
        self._kill_tree = kill_tree
        self._ops: WindowOps = ops if ops is not None else Win32WindowOps()
        self._title = title
        self._locate_sec = locate_sec
        self._retry_sec = retry_sec
        self._exit_wait_sec = exit_wait_sec
        self._monotonic = monotonic
        self._sleep = sleep
        self._browser_open = browser_open
        self._lock = threading.Lock()
        self._shown: _Shown | None = None
        self._dying: list[int] = []

    @property
    def window_handle(self) -> int | None:
        with self._lock:
            return self._shown.hwnd if self._shown is not None else None

    def open(self, url: str, display_id: int) -> None:
        self.close()
        if self._edge is None:
            self._browser_open(url)  # V25: no Edge, no window tracking
            return
        self._wait_for_exit()
        before = frozenset(self._ops.edge_windows())
        try:
            proc = self._popen(edge_command(self._edge, url, self._profile_dir))
        except OSError:
            self._browser_open(url)  # e.g. a stale --edge-path: the notice must still be shown (V25)
            return
        shown = _Shown(proc, before, self._monotonic())
        with self._lock:
            self._shown = shown
        if not self._locate(shown):
            threading.Thread(target=self._retry, args=(shown,), name="notice-topmost", daemon=True).start()

    def close(self) -> None:
        with self._lock:
            shown, self._shown = self._shown, None
            if shown is None:
                return
            shown.closed_by_us = True
            shown.stop.set()
        launcher = shown.proc.pid
        targets = [launcher] if shown.proc.poll() is None else []
        if shown.owner is not None and shown.owner != launcher:
            targets.append(shown.owner)  # e.g. the browser child the launcher handed over to
        if shown.owner is None and not targets:
            # The launcher is gone and no window was found: its browser child is an orphan in its tree.
            targets = self._ops.process_tree(launcher)[1:]
        killed = []
        for pid in targets:  # parents first: once a /T kill took the children, they are skipped
            if pid == launcher or self._ops.pid_alive(pid):
                self._kill_tree(pid)
                killed.append(pid)
        self._dying = killed

    def closed_by_user(self) -> bool:
        with self._lock:
            shown = self._shown
        if shown is None or shown.closed_by_us:
            return False
        if shown.hwnd is not None:
            return not self._ops.is_window(shown.hwnd)
        if self._monotonic() < shown.opened_at + self._locate_sec:
            return False
        if shown.proc.poll() is None or any(self._ops.pid_alive(p) for p in self._ops.process_tree(shown.proc.pid)[1:]):
            return False  # Edge still runs: its window may just be late or captioned differently
        self._locate(shown)  # last look before calling it closed
        return shown.hwnd is None

    def _wait_for_exit(self) -> None:
        """After our close, let the old Edge go before relaunching on the same profile (F10, ≤ 2 s)."""
        dying, self._dying = self._dying, []
        start = self._monotonic()
        while any(self._ops.pid_alive(pid) for pid in dying) and self._monotonic() - start < self._exit_wait_sec:
            self._sleep(0.05)

    def _pick(self, shown: _Shown) -> tuple[int, int] | None:
        new = {h: v for h, v in self._ops.edge_windows().items() if h not in shown.before and v[1]}
        if not new:
            return None
        tree = set(self._ops.process_tree(shown.proc.pid))
        ranked = sorted(new.items(), key=lambda kv: (kv[1][0] not in tree, kv[1][1] != self._title, kv[0]))
        hwnd, (pid, caption) = ranked[0]
        if pid not in tree and caption != self._title:
            return None  # someone else's Edge window
        return hwnd, pid

    def _locate(self, shown: _Shown) -> bool:
        """Find (once) and place the window; True when there is nothing more to do."""
        with self._lock:
            if shown is not self._shown or shown.closed_by_us:
                return True
            if shown.hwnd is None:
                picked = self._pick(shown)
                if picked is None:
                    return False
                shown.hwnd, shown.owner = picked
            if not shown.placed:
                shown.placed = self._ops.place(shown.hwnd)
            return shown.placed

    def _retry(self, shown: _Shown) -> None:
        deadline = shown.opened_at + self._locate_sec
        while self._monotonic() < deadline and not shown.stop.is_set():
            self._sleep(self._retry_sec)
            if self._locate(shown):
                return
