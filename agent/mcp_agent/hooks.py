"""Out-of-context WinEvent hooks for foreground, minimize/restore and title changes.

The hooks live on their own thread with a ``GetMessageW`` loop (out-of-context callbacks are
delivered through that thread's message queue). The callback stays light: three cheap Win32 reads,
a per-pid image cache and a hand-off to ``on_event``; it never lets an exception escape.
"""

from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable
from ctypes import wintypes as _wt
from datetime import UTC, datetime
from typing import Any

from mcp_agent import win32
from mcp_agent.coalesce import Kind, RawWinEvent

EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MINIMIZESTART = 0x0016
EVENT_SYSTEM_MINIMIZEEND = 0x0017
EVENT_OBJECT_NAMECHANGE = 0x800C
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
OBJID_WINDOW = 0
CHILDID_SELF = 0
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000
HOOK_RANGES = (
    (EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND),
    (EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND),
    (EVENT_OBJECT_NAMECHANGE, EVENT_OBJECT_NAMECHANGE),
)
IMAGE_CACHE_SEC = 30.0  # a pid can be reused; do not trust a cached image path for long
IMAGE_CACHE_MAX = 512

_KINDS: dict[int, Kind] = {
    EVENT_SYSTEM_FOREGROUND: "foreground",
    EVENT_SYSTEM_MINIMIZESTART: "minimize",
    EVENT_SYSTEM_MINIMIZEEND: "restore",
    EVENT_OBJECT_NAMECHANGE: "title",
}


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)

WINEVENTPROC = ctypes.WINFUNCTYPE(None, _wt.HANDLE, _wt.DWORD, _wt.HWND, _wt.LONG, _wt.LONG, _wt.DWORD, _wt.DWORD)


def _fn(dll: ctypes.WinDLL, name: str, restype: Any, *argtypes: Any) -> Any:
    f = getattr(dll, name)
    f.restype = restype
    f.argtypes = list(argtypes)
    return f


_LPMSG = ctypes.POINTER(_wt.MSG)
_GetCurrentThreadId = _fn(_kernel32, "GetCurrentThreadId", _wt.DWORD)
_SetWinEventHook = _fn(_user32, "SetWinEventHook", _wt.HANDLE, _wt.DWORD, _wt.DWORD, _wt.HMODULE, WINEVENTPROC,
                       _wt.DWORD, _wt.DWORD, _wt.DWORD)
_UnhookWinEvent = _fn(_user32, "UnhookWinEvent", _wt.BOOL, _wt.HANDLE)
_GetMessageW = _fn(_user32, "GetMessageW", ctypes.c_int, _LPMSG, _wt.HWND, _wt.UINT, _wt.UINT)
_PeekMessageW = _fn(_user32, "PeekMessageW", _wt.BOOL, _LPMSG, _wt.HWND, _wt.UINT, _wt.UINT, _wt.UINT)
_TranslateMessage = _fn(_user32, "TranslateMessage", _wt.BOOL, _LPMSG)
_DispatchMessageW = _fn(_user32, "DispatchMessageW", ctypes.c_ssize_t, _LPMSG)
_PostThreadMessageW = _fn(_user32, "PostThreadMessageW", _wt.BOOL, _wt.DWORD, _wt.UINT, _wt.WPARAM, _wt.LPARAM)


class WinEventHookThread(threading.Thread):
    def __init__(self, on_event: Callable[[RawWinEvent], None], *,
                 foreground: Callable[[], int] = win32.foreground_window,
                 text: Callable[[int], str] = win32.window_text,
                 pid_of: Callable[[int], int] = win32.window_pid,
                 image: Callable[[int], str | None] = win32.process_image,
                 monotonic: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        super().__init__(name="agent-winevent-hooks", daemon=True)
        self._on_event = on_event
        self._foreground, self._text, self._pid_of, self._image = foreground, text, pid_of, image
        self._monotonic, self._now = monotonic, now
        self._images: dict[int, tuple[str | None, float]] = {}
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._tid = 0
        self._last_foreground = 0
        self._proc = WINEVENTPROC(self._callback)  # keep a reference for as long as the hooks exist
        self.hook_count = 0  # hooks installed successfully
        self.errors = 0  # callbacks that failed (swallowed)

    def wait_ready(self, timeout: float) -> bool:
        return self._ready.wait(timeout)

    def run(self) -> None:
        hooks: list[int] = []
        msg = _wt.MSG()
        try:
            self._tid = int(_GetCurrentThreadId())
            _PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)  # create the queue for PostThreadMessageW
            flags = WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS
            for low, high in HOOK_RANGES:
                hook = _SetWinEventHook(low, high, None, self._proc, 0, 0, flags)
                if hook:
                    hooks.append(hook)
            self.hook_count = len(hooks)
            self._ready.set()
            while not self._stopping.is_set():
                got = _GetMessageW(ctypes.byref(msg), None, 0, 0)
                if got in (0, -1):  # WM_QUIT or an error
                    break
                _TranslateMessage(ctypes.byref(msg))
                _DispatchMessageW(ctypes.byref(msg))
        finally:
            for hook in hooks:
                _UnhookWinEvent(hook)
            self._ready.set()

    def stop(self) -> None:
        self._stopping.set()
        if self.ident is None:
            return  # never started
        self._ready.wait(2.0)
        if self._tid:
            _PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        self.join(2.0)

    def _callback(self, _hook: Any, event: int, hwnd: int | None, id_object: int, id_child: int,
                  _thread: int, _ms: int) -> None:
        self.handle(event, hwnd or 0, id_object, id_child)

    def handle(self, event: int, hwnd: int, id_object: int, id_child: int) -> None:
        """One WinEvent → at most one ``RawWinEvent``; never raises."""
        try:
            kind = _KINDS.get(event)
            if kind is None or not hwnd:
                return
            if kind == "foreground":
                self._last_foreground = hwnd
            elif kind == "title" and (id_object != OBJID_WINDOW or id_child != CHILDID_SELF
                                      or hwnd != (self._foreground() or self._last_foreground)):
                # GetForegroundWindow can answer 0 (seen on this PC while the foreground event had
                # just named a window): then the last EVENT_SYSTEM_FOREGROUND window counts.
                return
            pid = self._pid_of(hwnd)
            t = self._monotonic()
            self._on_event(RawWinEvent(t, kind, hwnd, pid, self._image_of(pid, t), self._text(hwnd), self._now()))
        except Exception:  # noqa: BLE001 - an exception must not escape into the hook callback
            self.errors += 1

    def _image_of(self, pid: int, t: float) -> str | None:
        cached = self._images.get(pid)
        if cached is not None and t - cached[1] < IMAGE_CACHE_SEC:
            return cached[0]
        if len(self._images) >= IMAGE_CACHE_MAX:
            self._images.clear()
        image = self._image(pid)
        self._images[pid] = (image, t)
        return image
