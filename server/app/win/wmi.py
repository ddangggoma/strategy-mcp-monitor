"""Process start/stop events from WMI (COM through pywin32), with a trace-or-poll fallback (V13).

``Win32_ProcessStartTrace``/``StopTrace`` need administrator or SYSTEM; when WMI denies them the
watch falls back to ``__InstanceCreationEvent``/``__InstanceDeletionEvent WITHIN 1`` (no admin,
1-second polling inside WMI). A watch and its ``next``/``close`` calls block and belong to one
collector thread: COM is initialized (MTA) on the thread that calls ``watch``.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import psutil

from app.win import IS_WINDOWS
from app.win.wts import filetime_to_dt

if IS_WINDOWS:
    import pythoncom
    import pywintypes
    import win32com.client

ProcessKind = Literal["start", "stop"]
WatchMode = Literal["trace", "poll"]

MONIKER = r"winmgmts:{impersonationLevel=impersonate}!\\.\root\cimv2"
TRACE_QUERIES: dict[str, str] = {
    "start": "SELECT * FROM Win32_ProcessStartTrace",
    "stop": "SELECT * FROM Win32_ProcessStopTrace",
}
POLL_QUERIES: dict[str, str] = {
    "start": "SELECT * FROM __InstanceCreationEvent WITHIN 1 WHERE TargetInstance ISA 'Win32_Process'",
    "stop": "SELECT * FROM __InstanceDeletionEvent WITHIN 1 WHERE TargetInstance ISA 'Win32_Process'",
}
WBEM_E_ACCESS_DENIED = -2147217405  # 0x80041003
WBEM_S_TIMEDOUT = -2147209215  # 0x80043001 as reported by SWbemEventSource.NextEvent
RPC_E_CHANGED_MODE = -2147417850  # 0x80010106: the thread already has another COM apartment


@dataclass(frozen=True)
class ProcessEvent:
    kind: ProcessKind
    at: datetime
    pid: int
    ppid: int | None
    name: str
    exe: str | None
    cmdline: str | None
    session_id: int | None
    user: str | None
    exit_code: int | None
    source: Literal["wmi:trace", "wmi:poll"]


class ProcessLookup(Protocol):
    def details(self, pid: int) -> tuple[str | None, str | None, str | None]:
        """``(exe, cmdline, user)`` of a running process; each is None when unavailable."""
        ...


class PsutilProcessLookup:
    """Reads exe, command line and owner with psutil; a denied, gone or zombie value is None."""

    def details(self, pid: int) -> tuple[str | None, str | None, str | None]:
        try:
            proc = psutil.Process(pid)
        except (psutil.Error, OSError, ValueError):
            return (None, None, None)
        return (
            _guard(proc.exe),
            _guard(lambda: subprocess.list2cmdline(proc.cmdline())),
            _guard(proc.username),
        )


def _guard(fn: Callable[[], str]) -> str | None:
    try:
        value = fn()
    except (psutil.Error, OSError):
        return None
    return value or None


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _opt_str(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def _time(props: Mapping[str, Any]) -> datetime:
    """``TIME_CREATED`` (FILETIME, int or the string WMI scripting gives a uint64) → aware UTC.

    A missing or zero value falls back to the receipt time."""
    raw = props.get("TIME_CREATED")
    at = filetime_to_dt(int(raw)) if raw not in (None, "") else None
    return at if at is not None else datetime.now(UTC)


def from_start_trace(props: Mapping[str, Any], lookup: ProcessLookup) -> ProcessEvent:
    pid = int(props["ProcessID"])
    exe, cmdline, user = lookup.details(pid)
    return ProcessEvent(
        kind="start",
        at=_time(props),
        pid=pid,
        ppid=_opt_int(props.get("ParentProcessID")),
        name=str(props.get("ProcessName") or ""),
        exe=exe,
        cmdline=cmdline,
        session_id=_opt_int(props.get("SessionID")),
        user=user,
        exit_code=None,
        source="wmi:trace",
    )


def from_stop_trace(props: Mapping[str, Any]) -> ProcessEvent:
    return ProcessEvent(
        kind="stop",
        at=_time(props),
        pid=int(props["ProcessID"]),
        ppid=_opt_int(props.get("ParentProcessID")),
        name=str(props.get("ProcessName") or ""),
        exe=None,
        cmdline=None,
        session_id=_opt_int(props.get("SessionID")),
        user=None,
        exit_code=_opt_int(props.get("ExitStatus")),
        source="wmi:trace",
    )


def from_instance_event(
    kind: ProcessKind,
    event_props: Mapping[str, Any],
    target: Mapping[str, Any],
    lookup: ProcessLookup | None,
) -> ProcessEvent:
    """An ``__InstanceCreationEvent``/``__InstanceDeletionEvent`` and its ``Win32_Process``."""
    pid = int(target["ProcessId"])
    user = lookup.details(pid)[2] if kind == "start" and lookup is not None else None
    return ProcessEvent(
        kind=kind,
        at=_time(event_props),
        pid=pid,
        ppid=_opt_int(target.get("ParentProcessId")),
        name=str(target.get("Name") or ""),
        exe=_opt_str(target.get("ExecutablePath")),
        cmdline=_opt_str(target.get("CommandLine")),
        session_id=_opt_int(target.get("SessionId")),
        user=user,
        exit_code=None,
        source="wmi:poll",
    )


class ProcessWatch(Protocol):
    mode: WatchMode

    def next(self, timeout_ms: int) -> ProcessEvent | None:
        """The next event, or None when ``timeout_ms`` passed without one."""
        ...

    def close(self) -> None: ...


class ProcessEventSource(Protocol):
    def watch(self, kind: ProcessKind) -> ProcessWatch: ...


def _scode(exc: Exception) -> int | None:
    """The WMI status of a ``com_error``: ``excepinfo[5]`` when present, else the HRESULT."""
    args: tuple[Any, ...] = tuple(getattr(exc, "args", ()))
    info = args[2] if len(args) > 2 else None
    if isinstance(info, tuple) and len(info) > 5 and info[5]:
        return int(info[5])
    return int(args[0]) if args and isinstance(args[0], int) else None


def _props(obj: Any) -> dict[str, Any]:
    return {p.Name: p.Value for p in obj.Properties_}


def _connect_cimv2() -> Any:
    return win32com.client.GetObject(MONIKER)


def _co_initialize() -> bool:
    """Join the MTA on this thread; True when this call must be balanced by ``CoUninitialize``.

    A thread that is already in another apartment (``import pythoncom`` makes the importing
    thread STA) keeps it: WMI works there too, and that initialization is not ours to undo."""
    try:
        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
    except pywintypes.com_error as exc:
        if _scode(exc) == RPC_E_CHANGED_MODE:
            return False
        raise
    return True


class WmiProcessSource:
    """The real ``ProcessEventSource`` (Windows only). ``connect`` returns an ``SWbemServices``;
    tests pass a fake one."""

    def __init__(
        self, lookup: ProcessLookup | None = None, *, connect: Callable[[], Any] | None = None
    ) -> None:
        self._lookup: ProcessLookup = lookup if lookup is not None else PsutilProcessLookup()
        self._connect = connect if connect is not None else _connect_cimv2

    def watch(self, kind: ProcessKind) -> WmiProcessWatch:
        if not IS_WINDOWS:
            raise RuntimeError("WMI is only available on Windows")
        owned = _co_initialize()
        try:
            services = self._connect()
            mode: WatchMode
            try:
                events = services.ExecNotificationQuery(TRACE_QUERIES[kind])
                mode = "trace"
            except pywintypes.com_error as exc:
                if _scode(exc) != WBEM_E_ACCESS_DENIED:
                    raise
                events = services.ExecNotificationQuery(POLL_QUERIES[kind])
                mode = "poll"
        except BaseException:
            if owned:
                pythoncom.CoUninitialize()
            raise
        return WmiProcessWatch(kind, mode, events, self._lookup, owned)


class WmiProcessWatch:
    """One semisynchronous WMI event query. Use it only on the thread that created it."""

    def __init__(
        self, kind: ProcessKind, mode: WatchMode, events: Any, lookup: ProcessLookup, owned: bool
    ) -> None:
        self.kind = kind
        self.mode: WatchMode = mode
        self._events: Any = events
        self._lookup = lookup
        self._owned = owned
        self.skipped = 0
        """Events dropped because they could not be mapped (missing or malformed properties)."""

    def next(self, timeout_ms: int) -> ProcessEvent | None:
        if self._events is None:
            raise RuntimeError("watch is closed")
        try:
            ev = self._events.NextEvent(timeout_ms)
        except pywintypes.com_error as exc:
            if _scode(exc) == WBEM_S_TIMEDOUT:
                return None
            raise
        try:
            props = _props(ev)
            if self.mode == "trace":
                if self.kind == "start":
                    return from_start_trace(props, self._lookup)
                return from_stop_trace(props)
            lookup = self._lookup if self.kind == "start" else None
            return from_instance_event(self.kind, props, _props(props["TargetInstance"]), lookup)
        except (KeyError, TypeError, ValueError, AttributeError):
            self.skipped += 1
            return None

    def close(self) -> None:
        if self._events is None:
            return
        self._events = None
        if self._owned:
            self._owned = False
            pythoncom.CoUninitialize()
