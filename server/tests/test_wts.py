import ctypes
import getpass
import ipaddress
import json
import sys
from datetime import UTC, datetime, timedelta

import pytest

from app.clock import SystemClock
from app.sessions.jsonsource import JsonFileWtsSource
from app.win import wts
from app.win.ffi import current_session_id
from app.win.wts import (
    CtypesWtsSource,
    WtsError,
    WtsSnapshot,
    filetime_to_dt,
    format_resolution,
    parse_client_address,
    protocol_name,
    state_name,
)
from tests.winfakes import FakeWtsSource


def test_filetime_to_dt():
    assert filetime_to_dt(0) is None
    assert filetime_to_dt(-5) is None
    assert filetime_to_dt(134382420000000000) == datetime(2026, 11, 4, 5, 0, tzinfo=UTC)
    assert filetime_to_dt(134382419705000000) == datetime(2026, 11, 4, 4, 59, 30, 500000, tzinfo=UTC)


def test_parse_client_address():
    assert parse_client_address(2, bytes([0, 0, 10, 0, 3, 21]) + bytes(14)) == "10.0.3.21"
    v6 = ipaddress.IPv6Address("fe80::1").packed
    assert parse_client_address(23, bytes(2) + v6 + bytes(2)) == "fe80::1"
    assert parse_client_address(0, bytes(20)) is None
    assert parse_client_address(2, bytes(20)) is None
    assert parse_client_address(23, bytes(20)) is None


def test_format_resolution():
    assert format_resolution(1920, 1080, 32) == "1920x1080@32"
    assert format_resolution(1280, 720, 8) == "1280x720@24"
    assert format_resolution(800, 600, 99) == "800x600"
    assert format_resolution(0, 0, 0) is None
    assert format_resolution(1920, 0, 32) is None


def test_state_and_protocol_names():
    assert [state_name(i) for i in (0, 4, 6)] == ["active", "disconnected", "listen"] and state_name(42) == "unknown"
    assert state_name(9) == "init" and state_name(-1) == "unknown"
    assert (protocol_name(0), protocol_name(2), protocol_name(1)) == ("console", "rdp", "other")


def test_json_source_resolves_self_and_idle(tmp_path, clock):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"sessions": [{
        "session_id": "self", "user": "hong", "domain": "CORP", "client_ip": "10.0.3.21", "client_name": "HONG-LAPTOP",
        "client_build": 26100, "resolution": "1920x1080@32", "logon_at": "2026-11-04T13:00:00+09:00",
        "connected_at": "2026-11-04T13:59:00+09:00", "idle_sec": 90, "locked": False}]}), "utf-8")
    snap = JsonFileWtsSource(p, clock, self_session_id=lambda: 7).snapshot()
    [s] = snap.sessions
    assert (snap.at, s.session_id, s.state, s.protocol, s.client_ip, s.client_build, s.locked, s.station) == \
        (clock.now(), 7, "active", "rdp", "10.0.3.21", 26100, False, "json-7")
    assert s.connected_at == datetime(2026, 11, 4, 4, 59, tzinfo=UTC)
    assert s.last_input_at == clock.now() - timedelta(seconds=90) and s.disconnected_at is None
    assert (s.user, s.domain, s.client_name, s.resolution) == ("hong", "CORP", "HONG-LAPTOP", "1920x1080@32")
    assert s.logon_at == datetime(2026, 11, 4, 4, 0, tzinfo=UTC)


def test_json_source_defaults_and_rereads_the_file(tmp_path, clock):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"sessions": [{"session_id": 3, "user": "kim"}]}), "utf-8")
    src = JsonFileWtsSource(p, clock, self_session_id=lambda: 7)
    [s] = src.snapshot().sessions
    assert (s.session_id, s.station, s.state, s.protocol, s.user) == (3, "json-3", "active", "rdp", "kim")
    assert (s.domain, s.client_name, s.client_ip, s.client_build, s.resolution) == (None, None, None, None, None)
    assert (s.logon_at, s.connected_at, s.disconnected_at, s.last_input_at, s.locked) == (None, None, None, None, None)
    p.write_text(json.dumps({"sessions": [
        {"session_id": 3, "user": "kim", "state": "disconnected", "disconnected_at": "2026-11-04T05:00:00+00:00"},
        {"session_id": "self", "user": "me", "protocol": "console", "locked": True}]}), "utf-8")
    a, b = src.snapshot().sessions
    assert (a.state, a.disconnected_at) == ("disconnected", datetime(2026, 11, 4, 5, 0, tzinfo=UTC))
    assert (b.session_id, b.protocol, b.locked) == (7, "console", True)
    p.write_text(json.dumps({"sessions": []}), "utf-8")
    assert src.snapshot().sessions == ()


@pytest.mark.parametrize("content", [
    None, "{", '{"sessions": [{"session_id": "x", "user": "a"}]}', '{"sessions": [{"session_id": 1}]}',
    '[]', '{"sessions": {}}', '{"sessions": [1]}', '{"sessions": [{"session_id": true, "user": "a"}]}',
    '{"sessions": [{"session_id": 1, "user": "a", "logon_at": "2026-11-04T13:00:00"}]}',
    '{"sessions": [{"session_id": 1, "user": "a", "logon_at": "yesterday"}]}',
    '{"sessions": [{"session_id": 1, "user": "a", "idle_sec": "9"}]}',
    '{"sessions": [{"session_id": 1, "user": "a", "locked": "no"}]}',
    '{"sessions": [{"session_id": 1, "user": "a", "state": "asleep"}]}',
    '{"sessions": [{"session_id": 1, "user": "a", "protocol": "ica"}]}',
    '{"sessions": [{"session_id": 1, "user": "a", "client_build": "x"}]}',
    '{"sessions": [{"session_id": 1, "user": "a", "client_ip": 5}]}',
])
def test_json_source_errors(tmp_path, clock, content):
    p = tmp_path / "s.json"
    if content is not None:
        p.write_text(content, "utf-8")
    with pytest.raises(WtsError):
        JsonFileWtsSource(p, clock).snapshot()


def test_fake_source_replays_items_then_repeats_the_last(clock):
    first, last = WtsSnapshot(clock.now(), ()), WtsSnapshot(clock.now() + timedelta(seconds=1), ())
    src = FakeWtsSource([first, WtsError("boom"), last])
    assert src.snapshot() is first
    with pytest.raises(WtsError):
        src.snapshot()
    assert src.snapshot() is last and src.snapshot() is last and src.calls == 4


@pytest.mark.winlive
def test_ctypes_source_sees_this_session():
    snap = CtypesWtsSource(SystemClock()).snapshot()
    mine = [s for s in snap.sessions if s.session_id == current_session_id()]
    assert len(mine) == 1 and mine[0].state == "active"
    assert mine[0].user.lower() == getpass.getuser().lower() and mine[0].logon_at is not None
    # F06: the desktop may be locked during an unattended run; the flag must still be read.
    assert mine[0].protocol in ("console", "rdp") and mine[0].locked in (True, False, None)
    assert all(s.state != "listen" for s in snap.sessions)
    assert snap.at.tzinfo is not None and mine[0].station


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 struct layout")
def test_wtsinfoex_struct_layout_matches_the_sdk():
    assert ctypes.sizeof(wts._WTSINFOEX_LEVEL1_W) == 224 and ctypes.sizeof(wts._WTSINFOEXW) == 232
    assert wts._WTSINFOEXW.Data.offset == 8 and wts._WTSINFOEX_LEVEL1_W.LogonTime.offset == 160
    assert ctypes.sizeof(wts._WTS_CLIENT_ADDRESS) == 24 and ctypes.sizeof(wts._WTS_CLIENT_DISPLAY) == 12


def test_ctypes_source_enumeration_failure_is_a_wts_error(monkeypatch, clock):
    class FailingApi:
        def WTSEnumerateSessionsW(self, *args):  # noqa: N802 (Win32 name)
            return 0

    monkeypatch.setattr(wts, "_wtsapi32", FailingApi())
    with pytest.raises(WtsError, match="WTSEnumerateSessionsW failed"):
        CtypesWtsSource(clock).snapshot()


def test_ctypes_source_off_windows_is_a_wts_error(monkeypatch, clock):
    monkeypatch.setattr(wts, "_wtsapi32", None)
    with pytest.raises(WtsError):
        CtypesWtsSource(clock).snapshot()


@pytest.mark.winlive
def test_ctypes_source_skips_a_session_whose_query_fails(monkeypatch):
    real = wts._read_session
    mine = current_session_id()

    def flaky(sid):
        if sid == mine:
            raise wts._QueryFailed(25, 2)  # ERROR_FILE_NOT_FOUND: the session went away
        return real(sid)

    monkeypatch.setattr(wts, "_read_session", flaky)
    snap = CtypesWtsSource(SystemClock()).snapshot()
    assert snap.sessions and all(s.session_id != mine for s in snap.sessions)
