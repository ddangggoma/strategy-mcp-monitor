"""ctypes bindings for the few kernel32 calls the server needs (Windows only).

On other platforms the module imports cleanly and the functions report "unknown" (``None``).
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any

from app.win import IS_WINDOWS

_kernel32: Any = None
if IS_WINDOWS:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    _kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.ProcessIdToSessionId.restype = wintypes.BOOL


def process_session_id(pid: int) -> int | None:
    """The Windows session id of process ``pid``, or None (no such process, no access, not Windows)."""
    if _kernel32 is None or not 0 <= pid <= 0xFFFFFFFF:
        return None
    sid = wintypes.DWORD()
    if not _kernel32.ProcessIdToSessionId(pid, ctypes.byref(sid)):
        return None
    return int(sid.value)


def current_session_id() -> int:
    """The Windows session id of this process; ``RuntimeError`` if it cannot be determined."""
    sid = process_session_id(os.getpid())
    if sid is None:
        raise RuntimeError("cannot determine the current Windows session id")
    return sid
