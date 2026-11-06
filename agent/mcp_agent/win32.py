"""ctypes bindings the agent needs. Every foreign function declares ``argtypes`` and ``restype``
(64-bit handles must not be truncated to ``int``), and the DLLs are private ``WinDLL`` instances so
these declarations never leak into ``ctypes.windll`` users."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_ntdll = ctypes.WinDLL("ntdll")


def _fn(dll: ctypes.WinDLL, name: str, restype: Any, *argtypes: Any) -> Any:
    f = getattr(dll, name)
    f.restype = restype
    f.argtypes = list(argtypes)
    return f


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259
HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040
MONITOR_DEFAULTTONEAREST = 0x00000002
PROCESS_COMMAND_LINE_INFORMATION = 60  # PROCESSINFOCLASS, Windows 8.1+

_GetCurrentProcessId = _fn(_kernel32, "GetCurrentProcessId", wintypes.DWORD)
_ProcessIdToSessionId = _fn(_kernel32, "ProcessIdToSessionId", wintypes.BOOL, wintypes.DWORD, wintypes.LPDWORD)
_GetTickCount64 = _fn(_kernel32, "GetTickCount64", ctypes.c_uint64)
_OpenProcess = _fn(_kernel32, "OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_GetExitCodeProcess = _fn(_kernel32, "GetExitCodeProcess", wintypes.BOOL, wintypes.HANDLE, wintypes.LPDWORD)
_CloseHandle = _fn(_kernel32, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
_CreateToolhelp32Snapshot = _fn(_kernel32, "CreateToolhelp32Snapshot", wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD)
_Process32FirstW = _fn(_kernel32, "Process32FirstW", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
_Process32NextW = _fn(_kernel32, "Process32NextW", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
_QueryFullProcessImageNameW = _fn(_kernel32, "QueryFullProcessImageNameW", wintypes.BOOL, wintypes.HANDLE,
                                  wintypes.DWORD, wintypes.LPWSTR, wintypes.LPDWORD)

_NtQueryInformationProcess = _fn(_ntdll, "NtQueryInformationProcess", ctypes.c_long, wintypes.HANDLE, ctypes.c_int,
                                 ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG))

_GetLastInputInfo = _fn(_user32, "GetLastInputInfo", wintypes.BOOL, ctypes.POINTER(LASTINPUTINFO))
_EnumWindows = _fn(_user32, "EnumWindows", wintypes.BOOL, WNDENUMPROC, wintypes.LPARAM)
_IsWindow = _fn(_user32, "IsWindow", wintypes.BOOL, wintypes.HWND)
_IsWindowVisible = _fn(_user32, "IsWindowVisible", wintypes.BOOL, wintypes.HWND)
_GetWindowThreadProcessId = _fn(_user32, "GetWindowThreadProcessId", wintypes.DWORD, wintypes.HWND, wintypes.LPDWORD)
_GetWindowTextLengthW = _fn(_user32, "GetWindowTextLengthW", ctypes.c_int, wintypes.HWND)
_GetWindowTextW = _fn(_user32, "GetWindowTextW", ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_GetClassNameW = _fn(_user32, "GetClassNameW", ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_GetWindowRect = _fn(_user32, "GetWindowRect", wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
_MonitorFromWindow = _fn(_user32, "MonitorFromWindow", wintypes.HMONITOR, wintypes.HWND, wintypes.DWORD)
_GetMonitorInfoW = _fn(_user32, "GetMonitorInfoW", wintypes.BOOL, wintypes.HMONITOR, ctypes.POINTER(MONITORINFO))
_SetWindowPos = _fn(_user32, "SetWindowPos", wintypes.BOOL, wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                    ctypes.c_int, ctypes.c_int, wintypes.UINT)
_SetForegroundWindow = _fn(_user32, "SetForegroundWindow", wintypes.BOOL, wintypes.HWND)
_GetForegroundWindow = _fn(_user32, "GetForegroundWindow", wintypes.HWND)


def current_session_id() -> int:
    sid = wintypes.DWORD()
    if not _ProcessIdToSessionId(_GetCurrentProcessId(), ctypes.byref(sid)):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(sid.value)


def process_session_id(pid: int) -> int | None:
    sid = wintypes.DWORD()
    if not _ProcessIdToSessionId(pid, ctypes.byref(sid)):
        return None
    return int(sid.value)


def process_command_line(pid: int) -> str | None:
    """The command line of ``pid`` (``PROCESS_QUERY_LIMITED_INFORMATION``: our own user's processes),
    or None when it cannot be read."""
    handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.ULONG(0)
        _NtQueryInformationProcess(handle, PROCESS_COMMAND_LINE_INFORMATION, None, 0, ctypes.byref(size))
        if size.value < ctypes.sizeof(UNICODE_STRING):
            return None
        buf = ctypes.create_string_buffer(size.value)
        if _NtQueryInformationProcess(handle, PROCESS_COMMAND_LINE_INFORMATION, buf, size, ctypes.byref(size)) < 0:
            return None  # NTSTATUS error
        text = UNICODE_STRING.from_buffer(buf)
        return ctypes.wstring_at(text.Buffer, text.Length // 2) if text.Buffer else ""
    finally:
        _CloseHandle(handle)


def idle_seconds() -> float:
    info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    if not _GetLastInputInfo(ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    # dwTime is the low 32 bits of the tick count; subtract modulo 2**32 so a wrap is harmless.
    return ((_GetTickCount64() & 0xFFFFFFFF) - info.dwTime) % 0x100000000 / 1000.0


def processes() -> dict[int, tuple[int, str]]:
    """pid -> (parent pid, image file name) for every process (Toolhelp32 snapshot)."""
    snap = _CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap is None or snap == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        out: dict[int, tuple[int, str]] = {}
        entry = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
        ok = _Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), entry.szExeFile)
            ok = _Process32NextW(snap, ctypes.byref(entry))
        return out
    finally:
        _CloseHandle(snap)


def process_tree(pid: int, image: str | None = None) -> list[int]:
    """``pid``, then its live descendants, parents before children. ``pid`` itself may be gone:
    children keep their parent's pid, so the tree of an exited launcher is still found. With
    ``image``, only descendants with that file name are followed (a reused parent pid cannot drag
    in unrelated processes)."""
    children: dict[int, list[int]] = {}
    for child, (ppid, exe) in processes().items():
        if child != ppid and (image is None or exe.lower() == image):
            children.setdefault(ppid, []).append(child)
    tree, seen, i = [pid], {pid}, 0
    while i < len(tree):
        for child in children.get(tree[i], []):
            if child not in seen:
                seen.add(child)
                tree.append(child)
        i += 1
    return tree


def pid_alive(pid: int) -> bool:
    handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(_GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        _CloseHandle(handle)


def window_text(hwnd: int) -> str:
    n = _GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    _GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def foreground_window() -> int:
    """The foreground window's handle, or 0 (none, e.g. while the desktop is locked or switching)."""
    return int(_GetForegroundWindow() or 0)


def process_image(pid: int) -> str | None:
    """Full image path of ``pid`` (``PROCESS_QUERY_LIMITED_INFORMATION``), or None if it cannot be opened."""
    handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not _QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return buf.value
    finally:
        _CloseHandle(handle)


def window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _GetClassNameW(hwnd, buf, 256)
    return buf.value


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    _GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def visible_top_windows() -> list[int]:
    found: list[int] = []

    @WNDENUMPROC
    def collect(hwnd: int, _lparam: int) -> bool:
        if hwnd and _IsWindowVisible(hwnd):
            found.append(int(hwnd))
        return True

    _EnumWindows(collect, 0)
    return found


EDGE_IMAGE = "msedge.exe"
CHROMIUM_WINDOW_CLASS = "Chrome_WidgetWin_1"


def edge_windows() -> dict[int, tuple[int, str]]:
    """Visible top-level Chromium windows of ANY msedge process: hwnd -> (owner pid, caption).

    An Edge ``--app`` window's caption is the page's ``document.title``. Edge may hand the URL to
    another browser process, so the window is not necessarily owned by the pid we launched (C1/F10).
    """
    procs = processes()
    out: dict[int, tuple[int, str]] = {}
    for hwnd in visible_top_windows():
        if window_class(hwnd) != CHROMIUM_WINDOW_CLASS:
            continue
        pid = window_pid(hwnd)
        if procs.get(pid, (0, ""))[1].lower() == EDGE_IMAGE:
            out[hwnd] = (pid, window_text(hwnd))
    return out


def is_window(hwnd: int) -> bool:
    return bool(_IsWindow(hwnd))


def place_topmost(hwnd: int) -> bool:
    """Centre ``hwnd`` on its monitor's work area, make it top-most and try to bring it forward."""
    rect = wintypes.RECT()
    if not _GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    width, height = rect.right - rect.left, rect.bottom - rect.top
    x, y = rect.left, rect.top
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    monitor = _MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if monitor and _GetMonitorInfoW(monitor, ctypes.byref(info)):
        work = info.rcWork
        x = work.left + max(0, (work.right - work.left - width) // 2)
        y = work.top + max(0, (work.bottom - work.top - height) // 2)
    if not _SetWindowPos(hwnd, HWND_TOPMOST, x, y, 0, 0, SWP_NOSIZE | SWP_SHOWWINDOW):
        return False
    _SetForegroundWindow(hwnd)  # may be refused by the foreground lock; top-most still holds
    return True
