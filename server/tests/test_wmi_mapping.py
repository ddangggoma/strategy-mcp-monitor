import os
import subprocess
import sys
from datetime import UTC, datetime

import pytest

from app.win.ffi import current_session_id
from app.win.wmi import (
    PsutilProcessLookup,
    WmiProcessSource,
    from_instance_event,
    from_start_trace,
    from_stop_trace,
)
from tests.winfakes import FakeLookup

FT = 134382420000000000  # 2026-11-04T05:00:00Z

def test_start_trace_uses_lookup_for_details():
    lk = FakeLookup({8812: (r"C:\Windows\System32\notepad.exe", "notepad.exe a.txt", "CORP\\hong")})
    ev = from_start_trace({"ProcessID": 8812, "ParentProcessID": 4100, "ProcessName": "notepad.exe", "SessionID": 2, "TIME_CREATED": str(FT)}, lk)
    assert (ev.kind, ev.at, ev.pid, ev.ppid, ev.name, ev.exe, ev.cmdline, ev.session_id, ev.user, ev.source) == \
        ("start", datetime(2026, 11, 4, 5, 0, tzinfo=UTC), 8812, 4100, "notepad.exe", r"C:\Windows\System32\notepad.exe",
         "notepad.exe a.txt", 2, "CORP\\hong", "wmi:trace")

def test_stop_trace_has_exit_code_and_no_lookup():
    ev = from_stop_trace({"ProcessID": 8812, "ParentProcessID": 4100, "ProcessName": "notepad.exe", "SessionID": 2, "TIME_CREATED": FT, "ExitStatus": 1})
    assert (ev.kind, ev.exit_code, ev.exe, ev.cmdline, ev.source) == ("stop", 1, None, None, "wmi:trace")

def test_instance_event_reads_target_instance():
    ev = from_instance_event("start", {"TIME_CREATED": FT}, {"ProcessId": 77, "ParentProcessId": 1, "Name": "PING.EXE",
        "ExecutablePath": r"C:\Windows\System32\PING.EXE", "CommandLine": "ping -n 3 127.0.0.1", "SessionId": 1},
        FakeLookup({77: (None, None, "CORP\\hong")}))
    assert (ev.pid, ev.cmdline, ev.session_id, ev.user, ev.source) == (77, "ping -n 3 127.0.0.1", 1, "CORP\\hong", "wmi:poll")

@pytest.mark.winlive
def test_wmi_source_sees_a_new_process():
    w = WmiProcessSource().watch("start")
    try:
        p = subprocess.Popen(["ping", "-n", "3", "127.0.0.1"], stdout=subprocess.DEVNULL)
        found = None
        for _ in range(8):
            ev = w.next(1000)
            if ev is not None and ev.pid == p.pid:
                found = ev; break
        p.wait()
    finally:
        w.close()
    assert found is not None and "ping" in (found.cmdline or "").lower() and found.session_id == current_session_id()
    assert w.mode in ("trace", "poll")


# --- beyond the plan sketch ---------------------------------------------------------------------

def test_instance_stop_does_not_look_up_and_missing_values_are_none():
    lk = FakeLookup({77: ("x.exe", "x", "CORP\\hong")})
    ev = from_instance_event("stop", {"TIME_CREATED": str(FT)},
                             {"ProcessId": 77, "ParentProcessId": None, "Name": None, "SessionId": None}, lk)
    assert (ev.kind, ev.pid, ev.ppid, ev.name, ev.exe, ev.cmdline, ev.session_id, ev.user, ev.exit_code) == \
        ("stop", 77, None, "", None, None, None, None, None)
    assert lk.calls == []


def test_start_trace_for_a_vanished_process_has_no_details():
    ev = from_start_trace({"ProcessID": 5, "ParentProcessID": 4, "ProcessName": "a.exe", "SessionID": 1,
                           "TIME_CREATED": FT}, FakeLookup({}))
    assert (ev.exe, ev.cmdline, ev.user, ev.session_id) == (None, None, None, 1)


def test_psutil_lookup_reads_this_process_and_tolerates_missing_ones():
    exe, cmdline, user = PsutilProcessLookup().details(os.getpid())
    assert exe is not None and exe.lower().endswith(".exe" if sys.platform == "win32" else "")
    assert cmdline is not None and "pytest" in cmdline
    assert user is not None and user != ""
    assert PsutilProcessLookup().details(0x7FFFFFF0) == (None, None, None)


# --- the COM glue, with a fake SWbemServices (no WMI involved) ----------------------------------

windows = pytest.mark.skipif(sys.platform != "win32", reason="pywin32 com_error")


def _com_error(scode: int):
    import pywintypes
    return pywintypes.com_error(-2147352567, "exception", (0, "SWbem", "text", None, 0, scode), None)


class _Prop:
    def __init__(self, name, value):
        self.Name = name
        self.Value = value


class _Obj:
    def __init__(self, **props):
        self.Properties_ = [_Prop(k, v) for k, v in props.items()]


class _EventSource:
    def __init__(self, items):
        self.items = list(items)
        self.timeouts = []

    def NextEvent(self, timeout_ms):
        self.timeouts.append(timeout_ms)
        item = self.items.pop(0) if self.items else _com_error(-2147209215)
        if isinstance(item, Exception):
            raise item
        return item


class _Services:
    def __init__(self, deny_trace, events):
        self.deny_trace = deny_trace
        self.events = events
        self.queries = []

    def ExecNotificationQuery(self, wql):
        self.queries.append(wql)
        if self.deny_trace and "Trace" in wql:
            raise _com_error(-2147217405)
        return self.events


@windows
def test_wmi_source_falls_back_to_polling_when_trace_is_denied():
    target = _Obj(ProcessId=77, ParentProcessId=1, Name="PING.EXE", ExecutablePath="p.exe",
                  CommandLine="ping", SessionId=1)
    events = _EventSource([_Obj(TIME_CREATED=str(FT), TargetInstance=target)])
    svc = _Services(True, events)
    w = WmiProcessSource(FakeLookup({77: (None, None, "CORP\\hong")}), connect=lambda: svc).watch("start")
    try:
        assert w.mode == "poll"
        assert svc.queries == [
            "SELECT * FROM Win32_ProcessStartTrace",
            "SELECT * FROM __InstanceCreationEvent WITHIN 1 WHERE TargetInstance ISA 'Win32_Process'",
        ]
        ev = w.next(250)
        assert ev is not None and (ev.pid, ev.user, ev.cmdline, ev.source, ev.at) == \
            (77, "CORP\\hong", "ping", "wmi:poll", datetime(2026, 11, 4, 5, 0, tzinfo=UTC))
        assert w.next(250) is None and events.timeouts == [250, 250]
    finally:
        w.close()
    w.close()  # idempotent


@windows
def test_wmi_source_uses_trace_when_allowed_and_maps_stop():
    events = _EventSource([_Obj(ProcessID=9, ParentProcessID=4, ProcessName="a.exe", SessionID=2,
                                TIME_CREATED=FT, ExitStatus=3)])
    svc = _Services(False, events)
    w = WmiProcessSource(FakeLookup({}), connect=lambda: svc).watch("stop")
    try:
        assert w.mode == "trace" and svc.queries == ["SELECT * FROM Win32_ProcessStopTrace"]
        ev = w.next(100)
        assert ev is not None and (ev.kind, ev.pid, ev.exit_code, ev.source) == ("stop", 9, 3, "wmi:trace")
    finally:
        w.close()


@windows
def test_wmi_source_skips_unmappable_events_and_raises_other_errors():
    import pywintypes
    events = _EventSource([_Obj(TIME_CREATED=FT), _com_error(-2147217406)])
    svc = _Services(False, events)
    w = WmiProcessSource(FakeLookup({}), connect=lambda: svc).watch("stop")
    try:
        assert w.next(100) is None and w.skipped == 1
        with pytest.raises(pywintypes.com_error):
            w.next(100)
    finally:
        w.close()


@windows
def test_wmi_source_other_query_errors_propagate():
    import pywintypes

    class Broken(_Services):
        def ExecNotificationQuery(self, wql):
            raise _com_error(-2147217394)

    with pytest.raises(pywintypes.com_error):
        WmiProcessSource(FakeLookup({}), connect=lambda: Broken(False, None)).watch("start")
