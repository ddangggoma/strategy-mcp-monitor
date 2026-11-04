from datetime import timedelta

import pytest

from app.monitor.history import McpHistory, ActionRecord, TransitionRecord
from app.monitor.models import McpState as S, Issue
from app.monitor.runner import ScriptResult
from app.monitor.store import McpStore
from app.users.store import UserStore
from tests.mcp_helpers import cfg


@pytest.fixture
def env(db, clock):
    users = UserStore(db, clock)
    o = users.create("o@x.com", "o", "developer", None)
    m = McpStore(db, clock, users).create(cfg(), o.id)
    return McpHistory(db, clock), m.id, clock


def test_sparkline_bounded(env):
    h, mid, clock = env
    for i in range(70):
        h.record(mid, clock.now(), True, float(i))
    h.record(mid, clock.now(), False, None)
    s = h.sparkline(mid)
    assert len(s) == 60 and s[-2] == 69.0 and s[-1] is None and h.last_check_at(mid) == clock.now()


def test_unknown_mcp_has_empty_live_state(env):
    h, mid, _ = env
    assert h.sparkline(mid) == [] and h.last_check_at(mid) is None and h.uptime(mid) is None


def test_uptime_pending_and_flushed(env, db):
    h, mid, clock = env
    assert h.uptime(mid) is None
    for ok in (True, True, True, False):
        h.record(mid, clock.now(), ok, 1.0 if ok else None)
    assert h.uptime(mid) == 0.75
    h.flush()
    assert h.uptime(mid) == 0.75
    assert McpHistory(db, clock).uptime(mid) == 0.75  # survives a restart


def test_uptime_window_and_not_counted(env):
    h, mid, clock = env
    h.record(mid, clock.now(), False, None)
    clock.advance(25 * 3600)
    h.record(mid, clock.now(), True, 2.0)
    h.record(mid, clock.now(), False, None, counted=False)
    assert h.uptime(mid) == 1.0 and h.sparkline(mid)[-1] is None


def test_uptime_hours_argument(env):
    h, mid, clock = env
    h.record(mid, clock.now(), False, None)
    clock.advance(2 * 3600)
    h.record(mid, clock.now(), True, 1.0)
    assert h.uptime(mid, hours=1) == 1.0
    assert h.uptime(mid, hours=3) == 0.5


def test_maintenance_checks_are_excluded_from_uptime_and_buckets(env, db):
    h, mid, clock = env
    h.record(mid, clock.now(), True, 1.0)
    for _ in range(5):  # maintenance: probed but not counted
        h.record(mid, clock.now(), False, None, counted=False)
    h.flush()
    assert h.uptime(mid) == 1.0
    assert db.query("SELECT ok, total FROM mcp_minutes")[0]["total"] == 1
    assert h.last_check_at(mid) == clock.now()
    assert h.sparkline(mid)[-5:] == [None] * 5


def test_not_counted_alone_creates_no_bucket(env, db):
    h, mid, clock = env
    h.record(mid, clock.now(), True, 1.0, counted=False)
    h.flush()
    assert h.uptime(mid) is None and db.query("SELECT * FROM mcp_minutes") == []


def test_rollover_buckets_and_additive_flush(env):
    h, mid, clock = env
    h.record(mid, clock.now(), True, 2.0)
    h.record(mid, clock.now(), True, 4.0)
    h.flush()
    h.record(mid, clock.now(), False, None)
    h.flush()
    clock.advance(60)
    h.record(mid, clock.now(), True, 1.0)
    b = h.buckets(mid, clock.now() - timedelta(hours=1))
    assert [(x.ok, x.total, x.avg_latency_ms, x.max_latency_ms) for x in b] == [
        (2, 3, 3.0, 4.0),
        (1, 1, 1.0, 1.0),
    ]


def test_rollover_writes_finished_minute_without_flush(env, db):
    h, mid, clock = env
    h.record(mid, clock.now(), True, 2.0)
    assert db.query("SELECT * FROM mcp_minutes") == []  # same minute: memory only
    clock.advance(59)
    h.record(mid, clock.now(), True, 4.0)  # 05:00:59 is still minute 05:00
    assert db.query("SELECT * FROM mcp_minutes") == []
    clock.advance(1)
    h.record(mid, clock.now(), False, None)  # 05:01:00 -> minute 05:00 goes to the DB
    rows = db.query("SELECT minute, ok, total, latency_sum, latency_n, latency_max FROM mcp_minutes")
    assert [tuple(r) for r in rows] == [("2026-11-04T05:00Z", 2, 2, 6.0, 2, 4.0)]
    assert h.uptime(mid) == pytest.approx(2 / 3)  # the open 05:01 bucket is included


def test_null_latency_never_overwrites_max(env, db):
    h, mid, clock = env
    h.record(mid, clock.now(), True, 5.0)
    h.flush()
    h.record(mid, clock.now(), False, None)  # latency_max = NULL in this flush
    h.flush()
    assert db.query("SELECT latency_max FROM mcp_minutes")[0][0] == 5.0
    clock.advance(60)  # failure-only bucket first, value second
    h.record(mid, clock.now(), False, None)
    h.flush()
    assert db.query("SELECT latency_max FROM mcp_minutes ORDER BY minute")[1][0] is None
    h.record(mid, clock.now(), True, 3.0)
    h.flush()
    assert db.query("SELECT latency_max FROM mcp_minutes ORDER BY minute")[1][0] == 3.0
    b = h.buckets(mid, clock.now() - timedelta(hours=1))
    assert b[0].max_latency_ms == 5.0 and b[1].avg_latency_ms == 3.0


def test_failure_only_bucket_has_no_latency(env):
    h, mid, clock = env
    h.record(mid, clock.now(), False, None)
    (b,) = h.buckets(mid, clock.now() - timedelta(hours=1))
    assert (b.ok, b.total, b.avg_latency_ms, b.max_latency_ms) == (0, 1, None, None)
    assert b.minute == clock.now().replace(second=0)


def test_buckets_merge_partial_flush_with_pending_and_respect_since(env):
    h, mid, clock = env
    h.record(mid, clock.now(), True, 2.0)
    h.flush()
    h.record(mid, clock.now(), True, 6.0)  # same minute, unflushed
    (b,) = h.buckets(mid, clock.now() - timedelta(minutes=1))
    assert (b.ok, b.total, b.avg_latency_ms, b.max_latency_ms) == (2, 2, 4.0, 6.0)
    assert h.buckets(mid, clock.now() + timedelta(minutes=1)) == []


def test_flush_drops_deleted_mcp_and_forget_clears_memory(env, db):
    h, mid, clock = env
    h.record(mid, clock.now(), True, 1.0)
    db.execute("DELETE FROM mcps WHERE id = ?", (mid,))
    h.flush()  # no FK error
    assert db.query("SELECT * FROM mcp_minutes") == []
    h.record(mid, clock.now(), True, 1.0)
    h.forget(mid)
    assert h.sparkline(mid) == [] and h.last_check_at(mid) is None
    h.flush()


def test_purge(env, db):
    h, mid, clock = env
    h.record(mid, clock.now(), True, 1.0)
    h.flush()
    clock.advance(8 * 86400)
    h.record(mid, clock.now(), True, 1.0)
    h.flush()
    assert h.purge() == 1 and len(db.query("SELECT * FROM mcp_minutes")) == 1


def test_purge_keeps_seven_days(env, db):
    h, mid, clock = env
    h.record(mid, clock.now(), True, 1.0)
    h.flush()
    clock.advance(7 * 86400)  # exactly at the retention boundary: kept
    assert h.purge() == 0
    clock.advance(60)
    assert h.purge() == 1


def test_transitions_and_actions(env):
    h, mid, clock = env
    h.record_transition(mid, TransitionRecord(clock.now(), S.HEALTHY, S.SUSPECT, Issue.PROCESS_DOWN))
    assert h.transitions(mid)[0].to_state == S.SUSPECT
    res = ScriptResult("ok", 0, 120, "out", "", False, False, 0, None, None)
    aid = h.record_action(
        ActionRecord("r1", mid, clock.now(), "restart", "stop", "auto", "UNRESPONSIVE", None, res)
    )
    got = h.action(mid, aid)
    assert (got.kind, got.requested, got.result.stdout) == ("stop", "restart", "out")
    assert h.actions(mid)[0].id == aid


def test_transition_roundtrip_and_tie_break(env):
    h, mid, clock = env
    h.record_transition(mid, TransitionRecord(clock.now(), S.HEALTHY, S.SUSPECT, Issue.UNRESPONSIVE))
    h.record_transition(mid, TransitionRecord(clock.now(), S.SUSPECT, S.HEALTHY, None))
    clock.advance(5)
    h.record_transition(mid, TransitionRecord(clock.now(), S.HEALTHY, S.MAINTENANCE, None))
    t = h.transitions(mid)
    assert [x.to_state for x in t] == [S.MAINTENANCE, S.HEALTHY, S.SUSPECT]  # at DESC, id DESC
    assert t[2].issue == Issue.UNRESPONSIVE and t[1].issue is None
    assert t[0].at == clock.now() and t[0].at.tzinfo is not None
    assert [x.to_state for x in h.transitions(mid, limit=1)] == [S.MAINTENANCE]


def test_action_roundtrip_tie_break_and_scoping(env, db):
    h, mid, clock = env
    users = UserStore(db, clock)
    actor = users.create("a@x.com", "a", "developer", None)
    full = ScriptResult("timeout", None, 1200, "o" * 10, "e" * 5, True, False, 1, "x", "sha")
    a1 = h.record_action(ActionRecord("r1", mid, clock.now(), "start", "start", "manual", "manual", actor.id, full))
    ok = ScriptResult("ok", 0, 5, "", "", False, False, 0, None, None)
    a2 = h.record_action(ActionRecord("r2", mid, clock.now(), "restart", "stop", "boot", "UNRESPONSIVE", None, ok))
    assert [a.id for a in h.actions(mid)] == [a2, a1]  # equal `at`: later insert first
    got = h.action(mid, a1)
    assert (got.run_id, got.at, got.trigger, got.reason, got.actor_id) == (
        "r1", clock.now(), "manual", "manual", actor.id)
    r = got.result
    assert (r.status, r.exit_code, r.duration_ms, r.stdout, r.stderr) == ("timeout", None, 1200, "o" * 10, "e" * 5)
    assert (r.stdout_truncated, r.stderr_truncated, r.killed, r.error) == (True, False, 1, "x")
    assert r.actual_sha256 is None  # not stored
    assert h.action(mid + 1, a1) is None and h.action(mid, 9999) is None
    assert len(h.actions(mid, limit=1)) == 1


def test_action_keeps_full_1mb_output(env):
    h, mid, clock = env
    big = "x" * 1_048_576
    res = ScriptResult("ok", 0, 1, big, big, False, False, 0, None, None)
    aid = h.record_action(ActionRecord("r", mid, clock.now(), "start", "start", "manual", "manual", None, res))
    got = h.action(mid, aid)
    assert len(got.result.stdout) == len(got.result.stderr) == 1_048_576
