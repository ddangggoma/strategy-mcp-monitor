import json
from datetime import UTC, datetime

import pytest

from app.logstore.normalize import CATEGORIES, OUTCOMES, SEARCH_MAX_CHARS, normalize
from app.logstore.reader import parse_line

TS = "2026-11-04T14:03:22.418+09:00"


def row(obj):
    obj = {"ts": TS, **obj}
    return normalize(obj, json.dumps(obj, ensure_ascii=False).encode(), "2026-11-04")


@pytest.mark.parametrize("obj,user,event,outcome,ip", [
    ({"cat": "activity.command", "event": "script_block", "user": "CORP\\hong", "client_ip": "10.0.3.21", "session_id": 2},
     "CORP\\hong", "script_block", None, "10.0.3.21"),
    ({"cat": "auth", "event": "login", "email": "a@x.com", "ip": "1.2.3.4", "ok": False}, "a@x.com", "login", "fail", "1.2.3.4"),
    ({"cat": "admin.audit", "action": "user_create", "actor_email": "a@x.com", "ip": "127.0.0.1", "result": "denied"},
     "a@x.com", "user_create", "denied", "127.0.0.1"),
    ({"cat": "mcp.action", "actor": "system", "status": "timeout", "name": "calc"}, None, None, "timeout", None),
    ({"cat": "session", "event": "logon_failed", "user": "hong"}, "hong", "logon_failed", "fail", None),
    ({"cat": "mcp.action", "actor": "d@x.com", "status": "weird"}, "d@x.com", None, None, None),
])
def test_normalize_actor_event_outcome(obj, user, event, outcome, ip):
    r = row(obj)
    assert (r.user, r.event, r.outcome, r.client_ip, r.cat, r.day) == (user, event, outcome, ip, obj["cat"], "2026-11-04")


def test_timestamp_and_session():
    r = row({"cat": "session", "session_id": 3})
    assert datetime.fromtimestamp(r.ts_ms / 1000, UTC) == datetime(2026, 11, 4, 5, 3, 22, 418000, tzinfo=UTC)
    assert r.session_id == 3 and row({"cat": "session", "session_id": True}).session_id is None


def test_search_text_flattens_and_caps():
    r = row({"cat": "admin.audit", "action": "mcp_update", "actor_email": "a@x.com", "target": {"id": 3, "fields": ["name", "port"]}})
    for word in ("mcp_update", "a@x.com", "3", "name", "port"):
        assert word in r.search.split()
    assert "admin.audit" not in r.search
    assert len(row({"cat": "system", "text": "x" * 10_000}).search) == SEARCH_MAX_CHARS


def test_same_line_same_hash():
    assert row({"cat": "system"}).line_hash == row({"cat": "system"}).line_hash
    assert len(row({"cat": "system"}).line_hash) == 8


# ---- beyond the plan's list ----

def test_categories_and_outcomes_are_fixed():
    assert CATEGORIES == ("session", "notice", "activity.process", "activity.command", "activity.window",
                          "activity.idle", "tamper", "mcp.health", "mcp.action", "auth", "admin.audit", "system")
    assert OUTCOMES == ("ok", "fail", "denied", "error", "failed", "timeout")


def test_caps_and_fallbacks():
    r = row({"cat": "system", "event": "e" * 300, "user": "u" * 300, "client_ip": "1" * 100})
    assert (len(r.event), len(r.user), len(r.client_ip)) == (100, 256, 64)
    # empty / non-string values fall through to the next key
    r = row({"cat": "auth", "user": "", "actor_email": None, "email": 7, "actor": "b@x.com", "client_ip": None, "ip": "9.9.9.9"})
    assert (r.user, r.client_ip) == ("b@x.com", "9.9.9.9")
    # the action stands in for the event only on admin.audit lines
    assert row({"cat": "system", "action": "x"}).event is None
    assert row({"cat": "admin.audit", "event": 5, "action": "user_delete"}).event == "user_delete"
    assert row({"cat": "auth", "ok": "yes"}).outcome is None and row({"cat": "auth", "ok": True}).outcome == "ok"
    assert row({"cat": "session", "event": "logon", "status": "ok"}).outcome is None
    assert row({"cat": "admin.audit", "result": ["ok"]}).outcome is None


def test_search_excludes_ts_cat_bools_floats_and_values_deeper_than_three():
    r = row({"cat": "system", "event": "audit.config", "ok": True, "ratio": 0.5, "n": -4,
             "values": {"a": {"b": {"c": "too-deep"}, "d": "kept"}}})
    words = r.search.split()
    assert "audit.config" in words and "-4" in words and "kept" in words
    assert "too-deep" not in words and "True" not in words and "0.5" not in words
    assert "2026-11-04T14:03:22.418+09:00" not in r.search and "values" not in words  # keys are not text


def test_raw_and_hash_come_from_the_original_bytes():
    raw = b'{"ts": "2026-11-04T14:00:00+09:00", "cat": "system", "t": "a\xffb"}'
    obj = parse_line(raw)
    assert obj is not None
    r = normalize(obj, raw, "2026-11-04")
    assert r.raw == raw.decode("utf-8", "replace") and "\ufffd" in r.raw
    other = normalize(obj, raw + b" ", "2026-11-04")
    assert other.line_hash != r.line_hash


# Every event shape Plans 3-4 emit (preflight D, E01-E13), as the real emitters write it.
REAL_EVENTS = [
    # E01 session tracker
    ({"cat": "session", "event": "connect", "connection_id": 7, "session_id": 2, "user": "DESKTOP-1\\hong",
      "domain": "DESKTOP-1", "client_ip": "10.0.0.5", "client_name": "PC-5", "client_build": 22631, "source": "wts"},
     ("connect", "DESKTOP-1\\hong", 2, "10.0.0.5", None)),
    # E02 session eventmap
    ({"cat": "session", "event": "logon_failed", "event_id": 4625, "record_id": 99, "source": "eventlog:4625",
      "user": "admin", "client_ip": "203.0.113.9", "status": "0xc000006d", "sub_status": "0xc000006a"},
     ("logon_failed", "admin", None, "203.0.113.9", "fail")),
    # E03 agent stopped on logoff
    ({"cat": "session", "event": "agent_stopped", "session_id": 3, "user": "hong", "pid": 10, "agent_pid": 11,
      "reason": "logoff"}, ("agent_stopped", "hong", 3, None, None)),
    # E04 notice
    ({"cat": "notice", "event": "notice_acknowledged", "user": "hong", "session_id": 2, "version": 4, "attempt": 1,
      "connection_id": 7, "elapsed_ms": 5300}, ("notice_acknowledged", "hong", 2, None, None)),
    # E05 process
    ({"cat": "activity.process", "event": "start", "name": "notepad.exe", "pid": 4242, "ppid": 1, "exe": "C:\\Windows\\notepad.exe",
      "cmdline": "notepad.exe a.txt", "session_id": 2, "user": "hong", "client_ip": "10.0.0.5"},
     ("start", "hong", 2, "10.0.0.5", None)),
    # E06 commands
    ({"cat": "activity.command", "event": "script_block", "shell": "powershell", "text": "Get-Process | Stop-Process",
      "script_block_id": "{a-b}", "path": None, "parts": 1, "truncated": False, "incomplete": False, "pid": 9,
      "source": "eventlog:4104", "record_id": 5, "session_id": 2, "user": "hong"},
     ("script_block", "hong", 2, None, None)),
    # E07 window / idle from the agent (with clock-skew fields)
    ({"cat": "activity.window", "event": "focus", "pid": 9, "exe": "chrome.exe", "title": "메모장", "source": "agent",
      "session_id": 2, "user": "hong", "skew_ms": 120}, ("focus", "hong", 2, None, None)),
    ({"cat": "activity.idle", "event": "idle", "idle_sec": 300, "source": "agent", "session_id": 2, "user": "hong"},
     ("idle", "hong", 2, None, None)),
    # E08 tamper
    ({"cat": "tamper", "event": "audit_config_changed", "key": "ProcessCreationIncludeCmdLine", "before": 1, "after": 0},
     ("audit_config_changed", None, None, None, None)),
    # E09 health
    ({"cat": "mcp.health", "mcp_id": 1, "name": "calc", "from": "UP", "to": "DOWN", "issue": "port_closed"},
     (None, None, None, None, None)),
    ({"cat": "mcp.health", "mcp_id": 1, "name": "calc", "alert": True, "issue": "slow"}, (None, None, None, None, None)),
    # E10 action
    ({"cat": "mcp.action", "mcp_id": 1, "name": "calc", "run_id": "r1", "kind": "restart", "requested": "restart",
      "trigger": "auto", "reason": None, "actor": "system", "status": "failed", "exit_code": 1, "duration_ms": 30.5,
      "killed": False, "error": None, "stdout": "", "stderr": "boom"}, (None, None, None, None, "failed")),
    # E11 auth on the Local channel carries windows_user (not a user facet)
    ({"cat": "auth", "event": "login", "email": "a@x.com", "channel": "local", "ip": "127.0.0.1", "user_agent": "UA",
      "ok": True, "windows_user": "DESKTOP-1\\hong"}, ("login", "a@x.com", None, "127.0.0.1", "ok")),
    # E12 admin audit, including an anonymous denied line
    ({"cat": "admin.audit", "actor_id": None, "actor_email": None, "action": "settings_update", "channel": "external",
      "ip": "198.51.100.1", "target": {"fields": ["retention_days"]}, "result": "denied"},
     ("settings_update", None, None, "198.51.100.1", "denied")),
    # E13 system
    ({"cat": "system", "event": "audit.config", "values": {"ProcessCreationIncludeCmdLine": 1, "ScriptBlockLogging": 1}},
     ("audit.config", None, None, None, None)),
    ({"cat": "system", "event": "collector.status", "source": "wmi", "ok": False, "error": "access denied"},
     ("collector.status", None, None, None, None)),
    ({"cat": "system", "event": "logstore.dropped", "count": 3}, ("logstore.dropped", None, None, None, None)),
]


@pytest.mark.parametrize("obj,expected", REAL_EVENTS, ids=[f"{o['cat']}:{o.get('event', o.get('action'))}" for o, _ in REAL_EVENTS])
def test_every_emitted_event_shape_parses_and_normalizes(obj, expected):
    raw = json.dumps({"ts": TS, **obj}, ensure_ascii=False).encode("utf-8")
    parsed = parse_line(raw)
    assert parsed is not None
    r = normalize(parsed, raw, "2026-11-04")
    assert r.cat in CATEGORIES
    assert (r.event, r.user, r.session_id, r.client_ip, r.outcome) == expected
    assert r.search and r.raw == raw.decode("utf-8")


def test_windows_user_on_auth_lines_is_searchable_but_not_the_user():
    r = row({"cat": "auth", "event": "login", "email": "a@x.com", "ok": True, "windows_user": "CORP\\kim"})
    assert r.user == "a@x.com" and "CORP\\kim" in r.search.split()
