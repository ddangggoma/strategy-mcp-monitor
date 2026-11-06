"""WTS (Remote Desktop Services) session source over ctypes, plus the pure parsers it uses.

``CtypesWtsSource.snapshot()`` is blocking: call it only from a collector thread (or
``asyncio.to_thread``), never on the event loop. Only the ``W`` entry points are used.
"""

from __future__ import annotations

import ctypes
import ipaddress
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from app.clock import Clock
from app.win import IS_WINDOWS

STATE_NAMES = ("active", "connected", "connect_query", "shadow", "disconnected", "idle", "listen",
               "reset", "down", "init")
"""``WTS_CONNECTSTATE_CLASS`` values 0..9, in order."""

WtsProtocol = Literal["console", "rdp", "other"]

_FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)
_AF_INET = 2
_AF_INET6 = 23
_COLOR_DEPTH_BITS = {1: 4, 2: 8, 4: 16, 8: 24, 16: 15, 24: 24, 32: 32}


def state_name(code: int) -> str:
    """The ``WTS_CONNECTSTATE_CLASS`` name for ``code``; ``"unknown"`` when out of range."""
    return STATE_NAMES[code] if 0 <= code < len(STATE_NAMES) else "unknown"


def protocol_name(code: int) -> WtsProtocol:
    """``WTSClientProtocolType``: 0 = console, 2 = RDP, anything else (1 = ICA, …) = other."""
    if code == 0:
        return "console"
    if code == 2:
        return "rdp"
    return "other"


def filetime_to_dt(value: int) -> datetime | None:
    """A FILETIME (100 ns ticks since 1601-01-01 UTC) as a UTC datetime; ``None`` for 0 or less."""
    if value <= 0:
        return None
    return _FILETIME_EPOCH + timedelta(microseconds=value // 10)


def parse_client_address(family: int, raw: bytes) -> str | None:
    """``WTS_CLIENT_ADDRESS.Address`` → text. IPv4 is ``Address[2:6]``, IPv6 ``Address[2:18]`` (V9)."""
    if family == _AF_INET:
        packed = bytes(raw[2:6])
        if len(packed) != 4 or not any(packed):
            return None
        return str(ipaddress.IPv4Address(packed))
    if family == _AF_INET6:
        packed = bytes(raw[2:18])
        if len(packed) != 16 or not any(packed):
            return None
        return str(ipaddress.IPv6Address(packed))
    return None


def format_resolution(h: int, v: int, depth_code: int) -> str | None:
    """``WTS_CLIENT_DISPLAY`` → ``"1920x1080@32"``; unknown colour-depth code → ``"800x600"``."""
    if h == 0 or v == 0:
        return None
    bits = _COLOR_DEPTH_BITS.get(depth_code)
    return f"{h}x{v}" if bits is None else f"{h}x{v}@{bits}"


@dataclass(frozen=True)
class WtsSession:
    session_id: int
    station: str
    state: str
    user: str
    """The logged-on user name, ``""`` when nobody is logged on."""
    domain: str | None
    client_name: str | None
    client_ip: str | None
    client_build: int | None
    protocol: WtsProtocol
    resolution: str | None
    logon_at: datetime | None
    connected_at: datetime | None
    disconnected_at: datetime | None
    last_input_at: datetime | None
    locked: bool | None
    """``SessionFlags``: True = locked, False = unlocked, None = unknown."""


@dataclass(frozen=True)
class WtsSnapshot:
    at: datetime
    sessions: tuple[WtsSession, ...]


class WtsError(Exception):
    """The session list could not be read."""


class WtsSource(Protocol):
    def snapshot(self) -> WtsSnapshot:
        """Blocking; call only from a collector thread. Raises ``WtsError`` on failure."""
        ...


# --- ctypes declarations --------------------------------------------------------------------

_WTS_CURRENT_SERVER_HANDLE = 0
_INFO_CLIENT_BUILD_NUMBER = 9
_INFO_CLIENT_NAME = 10
_INFO_CLIENT_ADDRESS = 14
_INFO_CLIENT_DISPLAY = 15
_INFO_CLIENT_PROTOCOL_TYPE = 16
_INFO_SESSION_INFO_EX = 25
_LISTEN = STATE_NAMES.index("listen")
_WTS_SESSIONSTATE_LOCK = 0
_WTS_SESSIONSTATE_UNLOCK = 1


class _WTS_SESSION_INFOW(ctypes.Structure):
    _fields_ = [
        ("SessionId", wintypes.DWORD),
        ("pWinStationName", wintypes.LPWSTR),
        ("State", ctypes.c_int),
    ]


class _WTSINFOEX_LEVEL1_W(ctypes.Structure):
    _fields_ = [
        ("SessionId", wintypes.ULONG),
        ("SessionState", ctypes.c_int),
        ("SessionFlags", wintypes.LONG),
        ("WinStationName", wintypes.WCHAR * 33),
        ("UserName", wintypes.WCHAR * 21),
        ("DomainName", wintypes.WCHAR * 18),
        ("LogonTime", ctypes.c_longlong),
        ("ConnectTime", ctypes.c_longlong),
        ("DisconnectTime", ctypes.c_longlong),
        ("LastInputTime", ctypes.c_longlong),
        ("CurrentTime", ctypes.c_longlong),
        ("IncomingBytes", wintypes.DWORD),
        ("OutgoingBytes", wintypes.DWORD),
        ("IncomingFrames", wintypes.DWORD),
        ("OutgoingFrames", wintypes.DWORD),
        ("IncomingCompressedBytes", wintypes.DWORD),
        ("OutgoingCompressedBytes", wintypes.DWORD),
    ]


class _WTSINFOEX_LEVEL_W(ctypes.Union):
    _fields_ = [("WTSInfoExLevel1", _WTSINFOEX_LEVEL1_W)]


class _WTSINFOEXW(ctypes.Structure):
    _fields_ = [("Level", wintypes.DWORD), ("Data", _WTSINFOEX_LEVEL_W)]


class _WTS_CLIENT_ADDRESS(ctypes.Structure):
    _fields_ = [("AddressFamily", wintypes.DWORD), ("Address", ctypes.c_ubyte * 20)]


class _WTS_CLIENT_DISPLAY(ctypes.Structure):
    _fields_ = [
        ("HorizontalResolution", wintypes.DWORD),
        ("VerticalResolution", wintypes.DWORD),
        ("ColorDepth", wintypes.DWORD),
    ]


_wtsapi32: Any = None
if IS_WINDOWS:
    _wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)  # type: ignore[attr-defined]
    _wtsapi32.WTSEnumerateSessionsW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_WTS_SESSION_INFOW)), ctypes.POINTER(wintypes.DWORD),
    ]
    _wtsapi32.WTSEnumerateSessionsW.restype = wintypes.BOOL
    _wtsapi32.WTSQuerySessionInformationW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD),
    ]
    _wtsapi32.WTSQuerySessionInformationW.restype = wintypes.BOOL
    _wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]
    _wtsapi32.WTSFreeMemory.restype = None


class _QueryFailed(Exception):
    pass


def _query(session_id: int, info_class: int, min_size: int) -> bytes:
    """``WTSQuerySessionInformationW`` → a copy of the returned buffer (freed here)."""
    buf = ctypes.c_void_p()
    size = wintypes.DWORD()
    if not _wtsapi32.WTSQuerySessionInformationW(
            _WTS_CURRENT_SERVER_HANDLE, session_id, info_class, ctypes.byref(buf), ctypes.byref(size)):
        raise _QueryFailed(info_class, ctypes.get_last_error())  # type: ignore[attr-defined]
    try:
        if not buf.value or size.value < min_size:
            raise _QueryFailed(info_class, "short buffer")
        return ctypes.string_at(buf.value, size.value)
    finally:
        if buf.value:
            _wtsapi32.WTSFreeMemory(buf)


def _text(raw: bytes) -> str:
    """A NUL-terminated UTF-16LE buffer as ``str``."""
    return raw.decode("utf-16-le", errors="replace").split("\0", 1)[0]


def _or_none(s: str) -> str | None:
    return s or None


def _locked(flags: int) -> bool | None:
    if flags == _WTS_SESSIONSTATE_LOCK:
        return True
    if flags == _WTS_SESSIONSTATE_UNLOCK:
        return False
    return None


def _read_session(session_id: int) -> WtsSession:
    ex = _WTSINFOEXW.from_buffer_copy(_query(session_id, _INFO_SESSION_INFO_EX, ctypes.sizeof(_WTSINFOEXW)))
    if ex.Level != 1:
        raise _QueryFailed(_INFO_SESSION_INFO_EX, f"level {ex.Level}")
    l1 = ex.Data.WTSInfoExLevel1
    client_name = _text(_query(session_id, _INFO_CLIENT_NAME, 0))
    addr = _WTS_CLIENT_ADDRESS.from_buffer_copy(
        _query(session_id, _INFO_CLIENT_ADDRESS, ctypes.sizeof(_WTS_CLIENT_ADDRESS)))
    build = wintypes.ULONG.from_buffer_copy(
        _query(session_id, _INFO_CLIENT_BUILD_NUMBER, ctypes.sizeof(wintypes.ULONG))).value
    disp = _WTS_CLIENT_DISPLAY.from_buffer_copy(
        _query(session_id, _INFO_CLIENT_DISPLAY, ctypes.sizeof(_WTS_CLIENT_DISPLAY)))
    proto = ctypes.c_ushort.from_buffer_copy(
        _query(session_id, _INFO_CLIENT_PROTOCOL_TYPE, ctypes.sizeof(ctypes.c_ushort))).value
    return WtsSession(
        session_id=session_id,
        station=l1.WinStationName,
        state=state_name(l1.SessionState),
        user=l1.UserName,
        domain=_or_none(l1.DomainName),
        client_name=_or_none(client_name),
        client_ip=parse_client_address(addr.AddressFamily, bytes(addr.Address)),
        client_build=build or None,
        protocol=protocol_name(proto),
        resolution=format_resolution(disp.HorizontalResolution, disp.VerticalResolution, disp.ColorDepth),
        logon_at=filetime_to_dt(l1.LogonTime),
        connected_at=filetime_to_dt(l1.ConnectTime),
        disconnected_at=filetime_to_dt(l1.DisconnectTime),
        last_input_at=filetime_to_dt(l1.LastInputTime),
        locked=_locked(l1.SessionFlags),
    )


class CtypesWtsSource:
    """The real ``WtsSource``: enumerates sessions on this machine (listeners are skipped)."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def snapshot(self) -> WtsSnapshot:
        if _wtsapi32 is None:
            raise WtsError("WTS is only available on Windows")
        infos = ctypes.POINTER(_WTS_SESSION_INFOW)()
        count = wintypes.DWORD()
        if not _wtsapi32.WTSEnumerateSessionsW(
                _WTS_CURRENT_SERVER_HANDLE, 0, 1, ctypes.byref(infos), ctypes.byref(count)):
            raise WtsError(f"WTSEnumerateSessionsW failed: {ctypes.get_last_error()}")  # type: ignore[attr-defined]
        try:
            ids = [infos[i].SessionId for i in range(count.value) if infos[i].State != _LISTEN]
        finally:
            _wtsapi32.WTSFreeMemory(infos)
        at = self._clock.now()
        sessions: list[WtsSession] = []
        for sid in ids:
            try:
                s = _read_session(sid)
            except _QueryFailed:
                continue  # the session went away between the enumeration and the query
            if s.state != "listen":
                sessions.append(s)
        return WtsSnapshot(at=at, sessions=tuple(sessions))
