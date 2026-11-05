import asyncio
import json
import sys
from datetime import timedelta

import pytest

from app.clock import to_kst_iso
from app.monitor.engine import ActionInProgressError
from app.monitor.models import Issue, Mcp
from app.monitor.models import McpState as S
from app.monitor.probes import ProbeResult
from app.monitor.scripts import ScriptUpload
from app.monitor.store import McpNotFoundError
from tests.fakes import ok_result
from tests.mcp_helpers import make_user, seed_mcp

BOARD_KEYS = {"id", "name", "state", "issue", "latency_ms", "sparkline", "uptime_24h", "last_check_at",
              "action_due_at", "action_in_sec", "maintenance", "running"}


async def logs(services, cat):
    await services.log.flush()
    return [e for f in services.paths.logs_dir.glob("*.jsonl") for e in map(json.loads, f.read_text("utf-8").splitlines()) if e["cat"] == cat]

async def crash_to_action(services, m, issue=Issue.PROCESS_DOWN):
    mon = services.monitor; services.monitor._prober.set_check(m.id, issue)
    await mon.issue_round(); await mon.wait_idle()
    services.clock.advance(30); await mon.confirm_round(); await mon.wait_idle()

async def test_ping_round_records_history(services):
    m = seed_mcp(services, make_user(services, "o@x.com")); sub = services.bus.subscribe()
    services.monitor._prober.set_probe(m.id, ProbeResult(True, 4.2, None))
    await services.monitor.ping_round(); await services.monitor.wait_idle()
    assert services.history.sparkline(m.id)[-1] == 4.2 and m.id in sub.dirty

async def test_crash_runs_start_and_records(services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    await crash_to_action(services, m)
    call = services.monitor._runner.calls[-1]
    assert call.path.name == "start.bat" and call.lock_key == m.id and call.timeout_sec == 120
    assert {k: call.env[k] for k in ("MCP_ID", "MCP_NAME", "MCP_HOST", "MCP_PORT", "MCP_PID", "MCP_REASON", "MCP_TRIGGER", "MCP_ACTOR")} == \
        {"MCP_ID": str(m.id), "MCP_NAME": "calc", "MCP_HOST": "127.0.0.1", "MCP_PORT": "9102", "MCP_PID": "", "MCP_REASON": "PROCESS_DOWN", "MCP_TRIGGER": "auto", "MCP_ACTOR": "system"}
    a = services.history.actions(m.id)[0]
    assert (a.kind, a.trigger, a.result.status) == ("start", "auto", "ok")
    assert services.monitor.engine(m.id).state == S.ACTION
    assert [e["to"] for e in await logs(services, "mcp.health")] == ["SUSPECT", "ACTION"]
    assert (await logs(services, "mcp.action"))[0]["status"] == "ok"

async def test_restart_fallback_stop_then_start(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    await crash_to_action(services, m, Issue.UNRESPONSIVE)
    assert [c.path.name for c in services.monitor._runner.calls] == ["stop.bat", "start.bat"]
    assert [a.kind for a in services.history.actions(m.id)] == ["start", "stop"]

async def test_tamper_logged(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    services.monitor._runner.results.append(ok_result(status="error", exit_code=None, error="hash_mismatch", actual_sha256="ab" * 32))
    await crash_to_action(services, m)
    t = (await logs(services, "tamper"))[0]
    assert (t["mcp_id"], t["kind"], t["actual_sha256"]) == (m.id, "start", "ab" * 32)
    assert services.monitor.engine(m.id).state == S.SUSPECT

async def test_slow_script_does_not_block_and_conflicts(services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    services.monitor._runner.gate = asyncio.Event()
    services.monitor.manual_action(m.id, "start", owner); await asyncio.sleep(0)
    await asyncio.wait_for(services.monitor.ping_round(), 1.0)
    with pytest.raises(ActionInProgressError): services.monitor.manual_action(m.id, "restart", owner)
    with pytest.raises(ActionInProgressError): services.monitor.remove(m.id)
    services.monitor._runner.gate.set(); await services.monitor.wait_idle()
    assert services.monitor._runner.calls[-1].env["MCP_ACTOR"] == "o@x.com"

async def test_manual_stop_persists_maintenance(services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    services.monitor.manual_action(m.id, "stop", owner); await services.monitor.wait_idle()
    assert services.mcps.get(m.id).config.maintenance is True
    services.monitor.remove(m.id); services.monitor.add(services.mcps.get(m.id))
    assert services.monitor.engine(m.id).state == S.MAINTENANCE

async def test_boot_autostart(services):
    m = seed_mcp(services, make_user(services, "o@x.com"), autostart_on_boot=True)
    services.monitor._prober.set_check(m.id, Issue.PROCESS_DOWN)
    services.monitor.remove(m.id)
    await services.monitor.start(run_loops=False); await services.monitor.wait_idle()
    assert services.monitor._runner.calls[-1].env["MCP_TRIGGER"] == "boot"

async def test_runner_exception_isolated(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    services.monitor._runner.raise_next = RuntimeError("boom")
    await crash_to_action(services, m)
    assert services.monitor.engine(m.id).state == S.SUSPECT
    assert services.history.actions(m.id)[0].result.error == "internal"
    assert any("boom" in e.get("error", "") for e in await logs(services, "system"))

async def test_no_overlapping_checks_for_same_mcp(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    services.monitor._prober.delay = 0.3; services.monitor._prober.set_check(m.id, Issue.UNRESPONSIVE)
    await services.monitor.issue_round(); await services.monitor.wait_idle()
    services.monitor._prober.check_calls.clear()
    for _ in range(3): await services.monitor.confirm_round()
    await services.monitor.wait_idle()
    assert services.monitor._prober.check_calls == [m.id]

async def test_probes_run_concurrently(services):
    owner = make_user(services, "o@x.com")
    for i in range(50): seed_mcp(services, owner, name=f"m{i}", port=10000 + i)
    services.monitor._prober.delay = 0.3
    t = asyncio.get_running_loop().time()
    await services.monitor.ping_round(); await services.monitor.wait_idle()
    assert asyncio.get_running_loop().time() - t < 1.0

async def test_timeout_setting_passed(services):
    m = seed_mcp(services, make_user(services, "o@x.com"), script_timeout_sec=30)
    await crash_to_action(services, m)
    assert services.monitor._runner.calls[-1].timeout_sec == 30

async def test_loops_follow_settings(services):
    seed_mcp(services, make_user(services, "o@x.com"))
    services.settings.update({"ping_interval_sec": 1})
    await services.monitor.start(run_loops=True)
    await asyncio.sleep(2.5)
    assert len(services.monitor._prober.probe_calls) >= 2


# ---- additions beyond the brief's snippet (controller rulings F5, F6, F18, F24, F29 and carries) ----

async def test_loops_reread_settings_every_round(services):
    """F18: a settings change applies from the next round on, without restarting the monitor."""
    seed_mcp(services, make_user(services, "o@x.com"))
    services.settings.update({"ping_interval_sec": 1})
    calls = services.monitor._prober.probe_calls
    await services.monitor.start(run_loops=True)
    await asyncio.sleep(1.5)
    assert len(calls) == 2  # t=0 and t=1
    services.settings.update({"ping_interval_sec": 300})
    await asyncio.sleep(1.0)
    assert len(calls) == 3  # t=2 ran, then the sleep re-read 300 s
    await asyncio.sleep(1.5)
    assert len(calls) == 3

async def test_confirm_not_blocked_by_inflight_ping(services):
    """F6: the ping and the check have separate in-flight guards."""
    m = seed_mcp(services, make_user(services, "o@x.com"))
    mon = services.monitor; mon._prober.set_check(m.id, Issue.UNRESPONSIVE)
    await mon.issue_round(); await mon.wait_idle()
    assert mon.engine(m.id).state == S.SUSPECT
    mon._prober.delay = 0.5
    await mon.ping_round(); await mon.ping_round()  # second one skipped: ping already in flight
    await mon.confirm_round(); await asyncio.sleep(0)
    assert mon._prober.probe_calls == [m.id] and mon._prober.check_calls[-1] == m.id
    assert len(mon._prober.check_calls) == 2
    await mon.wait_idle()

async def test_manual_stop_then_unset_maintenance_is_healthy(services):
    """F5: after a manual stop the cached config carries maintenance=True, so clearing it is a real change."""
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    mon = services.monitor
    mon.manual_action(m.id, "stop", owner); await mon.wait_idle()
    assert mon.engine(m.id).config.maintenance is True and mon.board_item(m.id)["maintenance"] is True
    _, after = services.mcps.update(m.id, {"maintenance": False})
    mon.reconfigure(after)
    assert mon.engine(m.id).state == S.HEALTHY and mon.board_item(m.id)["maintenance"] is False

async def test_rejected_manual_action_writes_nothing(services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    mon = services.monitor; mon._runner.gate = asyncio.Event()
    mon.manual_action(m.id, "start", owner); await asyncio.sleep(0)
    with pytest.raises(ActionInProgressError): mon.manual_action(m.id, "stop", owner)
    assert services.mcps.get(m.id).config.maintenance is False
    mon._runner.gate.set(); await mon.wait_idle()

async def test_manual_start_leaves_maintenance(services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner, maintenance=True)
    mon = services.monitor
    assert mon.engine(m.id).state == S.MAINTENANCE
    run_id = mon.manual_action(m.id, "start", owner); await mon.wait_idle()
    assert len(run_id) == 32 and services.history.actions(m.id)[0].run_id == run_id
    assert services.mcps.get(m.id).config.maintenance is False
    assert mon.engine(m.id).state == S.ACTION and mon.board_item(m.id)["maintenance"] is False
    a = services.history.actions(m.id)[0]
    assert (a.trigger, a.reason, a.actor_id) == ("manual", "manual", owner.id)

async def test_manual_action_unknown_mcp(services):
    with pytest.raises(McpNotFoundError):
        services.monitor.manual_action(999, "start", make_user(services, "o@x.com"))

async def test_maintenance_checks_not_counted(services):
    m = seed_mcp(services, make_user(services, "o@x.com"), maintenance=True)
    await services.monitor.ping_round(); await services.monitor.wait_idle()
    assert services.history.sparkline(m.id) == [5.0] and services.history.uptime(m.id) is None

async def test_pid_passed_to_scripts(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    await crash_to_action(services, m, Issue.UNRESPONSIVE)  # fake check reports no pid
    services.monitor._prober.set_check(m.id, Issue.UNRESPONSIVE, pid=4242)
    services.clock.advance(31); await services.monitor.confirm_round(); await services.monitor.wait_idle()
    assert services.monitor.engine(m.id).state == S.SUSPECT  # grace over -> RECOVERING -> still hung
    services.clock.advance(30); await services.monitor.confirm_round(); await services.monitor.wait_idle()
    assert services.monitor._runner.calls[-1].env["MCP_PID"] == "4242"

async def test_restart_script_used_when_present(services):
    scripts = {"start": ScriptUpload(".bat", "exit /b 0"), "stop": ScriptUpload(".bat", "exit /b 0"),
               "restart": ScriptUpload(".cmd", "exit /b 0")}
    m = seed_mcp(services, make_user(services, "o@x.com"), scripts=scripts)
    await crash_to_action(services, m, Issue.UNRESPONSIVE)
    call = services.monitor._runner.calls[-1]
    assert [c.path.name for c in services.monitor._runner.calls] == ["restart.cmd"]
    assert call.expected_sha256 == services.scripts.get(m.id, "restart").sha256

async def test_fallback_runs_start_even_if_stop_fails_and_engine_gets_start_result(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    services.monitor._runner.results.extend([ok_result(status="failed", exit_code=1), ok_result()])
    await crash_to_action(services, m, Issue.UNRESPONSIVE)
    acts = services.history.actions(m.id)
    assert [(a.requested, a.kind, a.result.status) for a in acts] == [("restart", "start", "ok"), ("restart", "stop", "failed")]
    assert len({a.run_id for a in acts}) == 1
    assert services.monitor.engine(m.id).state == S.ACTION  # start ok: waiting out the startup grace
    logged = await logs(services, "mcp.action")
    assert [(e["kind"], e["requested"], e["status"]) for e in logged] == [("stop", "restart", "failed"), ("start", "restart", "ok")]

async def test_action_log_fields_and_output_truncated(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    services.monitor._runner.results.append(ok_result(stdout="x" * 5000, stderr="é" * 5000, killed=0))
    await crash_to_action(services, m)
    e = (await logs(services, "mcp.action"))[0]
    assert set(e) == {"ts", "cat", "mcp_id", "name", "run_id", "kind", "requested", "trigger", "reason", "actor",
                      "status", "exit_code", "duration_ms", "killed", "error", "stdout", "stderr"}
    assert len(e["stdout"]) == 4096 and len(e["stderr"]) == 4096
    assert (e["name"], e["reason"], e["actor"], e["trigger"]) == ("calc", "PROCESS_DOWN", "system", "auto")
    assert len(services.history.actions(m.id)[0].result.stdout) == 5000  # the DB row keeps the full capture

async def test_action_event_only_to_authed_subscribers(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    anon, authed = services.bus.subscribe(), services.bus.subscribe(authed=True)
    await crash_to_action(services, m)
    assert [ev for ev, _ in anon.events] == []
    (ev, data), = list(authed.events)
    assert ev == "action" and set(data) == {"run_id", "mcp_id", "kind", "trigger", "status", "exit_code", "duration_ms"}
    assert (data["mcp_id"], data["kind"], data["status"]) == (m.id, "start", "ok")

async def test_tamper_log_fields(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    services.monitor._runner.results.append(ok_result(status="error", exit_code=None, error="hash_mismatch", actual_sha256="cd" * 32))
    await crash_to_action(services, m)
    t = (await logs(services, "tamper"))[0]
    info = services.scripts.get(m.id, "start")
    assert (t["path"], t["expected_sha256"]) == (str(info.path), info.sha256)

async def test_runner_internal_result_logged_as_system(services):
    """Task 7 carry: a runner-reported internal error surfaces as a system event with its detail."""
    m = seed_mcp(services, make_user(services, "o@x.com"))
    services.monitor._runner.results.append(ok_result(status="error", exit_code=None, error="internal", stderr="RuntimeError('bug')"))
    await crash_to_action(services, m)
    sys_events = await logs(services, "system")
    assert any(e.get("mcp_id") == m.id and "bug" in e.get("error", "") for e in sys_events)

async def test_port_lookup_error_logged_rate_limited(services):
    """Task 9 carry: a failed port lookup is reported as a system event (once per 10 minutes per MCP)."""
    m = seed_mcp(services, make_user(services, "o@x.com"))
    mon = services.monitor; mon._prober.set_check(m.id, None, error="port_lookup:AccessDenied")
    for _ in range(3):
        await mon.issue_round(); await mon.wait_idle()
    services.clock.advance(601); await mon.issue_round(); await mon.wait_idle()
    events = [e for e in await logs(services, "system") if "port_lookup" in e.get("error", "")]
    assert len(events) == 2 and events[0]["mcp_id"] == m.id

async def test_alert_only_issue_logs_alert(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    await crash_to_action(services, m, Issue.NETWORK_DOWN)
    health = await logs(services, "mcp.health")
    assert [(e.get("to"), e.get("alert"), e["issue"]) for e in health] == [("SUSPECT", None, "NETWORK_DOWN"), (None, True, "NETWORK_DOWN")]
    assert services.monitor._runner.calls == [] and services.monitor.engine(m.id).state == S.SUSPECT

async def test_transitions_recorded(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    await crash_to_action(services, m)
    assert [(t.from_state, t.to_state) for t in services.history.transitions(m.id)] == [(S.SUSPECT, S.ACTION), (S.HEALTHY, S.SUSPECT)]
    e = (await logs(services, "mcp.health"))[0]
    assert (e["mcp_id"], e["name"], e["from"], e["to"], e["issue"]) == (m.id, "calc", "HEALTHY", "SUSPECT", "PROCESS_DOWN")

async def test_board_item_and_order(services):
    owner = make_user(services, "o@x.com")
    b = seed_mcp(services, owner, name="beta", port=9201); a = seed_mcp(services, owner, name="Alpha", port=9202)
    mon = services.monitor
    assert [i["name"] for i in mon.board()] == ["Alpha", "beta"] and mon.board_item(999) is None
    item = mon.board_item(b.id)
    assert set(item) == BOARD_KEYS
    assert item == {"id": b.id, "name": "beta", "state": "HEALTHY", "issue": None, "latency_ms": None, "sparkline": [],
                    "uptime_24h": None, "last_check_at": None, "action_due_at": None, "action_in_sec": None,
                    "maintenance": False, "running": None}
    mon._prober.set_check(b.id, Issue.PROCESS_DOWN)
    await mon.issue_round(); await mon.wait_idle()
    services.clock.advance(12.34)
    item = mon.board_item(b.id)
    due = services.clock.now() - timedelta(seconds=12.34) + timedelta(seconds=30)
    assert (item["state"], item["issue"], item["action_in_sec"], item["action_due_at"]) == ("SUSPECT", "PROCESS_DOWN", 17.7, to_kst_iso(due))
    assert item["last_check_at"] == to_kst_iso(services.clock.now() - timedelta(seconds=12.34))
    assert item["sparkline"] == [None] and item["uptime_24h"] == 0.0 and item["latency_ms"] is None
    services.clock.advance(60)
    assert mon.board_item(b.id)["action_in_sec"] == 0.0
    await mon.ping_round(); await mon.wait_idle()
    assert mon.board_item(a.id)["latency_ms"] == 5.0 and mon.board_item(a.id)["sparkline"] == [5.0, 5.0]  # check + ping

async def test_board_running_kind(services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    mon = services.monitor; mon._runner.gate = asyncio.Event()
    mon.manual_action(m.id, "restart", owner); await asyncio.sleep(0)
    assert mon.board_item(m.id)["running"] == "restart"
    mon._runner.gate.set(); await mon.wait_idle()
    assert mon.board_item(m.id)["running"] is None

async def test_remove_forgets_everything(services):
    m = seed_mcp(services, make_user(services, "o@x.com")); mon = services.monitor
    await mon.ping_round(); await mon.wait_idle()
    sub = services.bus.subscribe()
    mon.remove(m.id)
    assert mon.engine(m.id) is None and mon.board_item(m.id) is None and mon.board() == []
    assert services.history.sparkline(m.id) == [] and mon._prober.forgotten == [m.id] and m.id in sub.dirty
    mon.remove(m.id)  # idempotent

async def test_result_of_removed_mcp_is_dropped(services):
    m = seed_mcp(services, make_user(services, "o@x.com")); mon = services.monitor
    mon._prober.delay = 0.2
    await mon.ping_round(); await mon.issue_round(); await asyncio.sleep(0)
    mon.remove(m.id)
    await mon.wait_idle()
    assert services.history.sparkline(m.id) == [] and mon.engine(m.id) is None

async def test_reconfigure_maintenance_and_url(services):
    m = seed_mcp(services, make_user(services, "o@x.com")); mon = services.monitor
    _, after = services.mcps.update(m.id, {"maintenance": True})
    mon.reconfigure(after)
    assert mon.engine(m.id).state == S.MAINTENANCE and mon._prober.forgotten == []
    _, after = services.mcps.update(m.id, {"port": 9333, "action_delay_sec": 5})
    mon.reconfigure(after)
    assert mon._prober.forgotten == [m.id] and mon.engine(m.id).config.action_delay_sec == 5
    with pytest.raises(McpNotFoundError):
        mon.reconfigure(Mcp(999, after.config, None, None, after.created_at))

async def test_add_twice_rejected(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    with pytest.raises(ValueError): services.monitor.add(m)

async def test_start_keeps_existing_engines_and_boots_only_new(services):
    owner = make_user(services, "o@x.com")
    kept = seed_mcp(services, owner, name="kept", port=9301, autostart_on_boot=True)
    fresh = seed_mcp(services, owner, name="fresh", port=9302, autostart_on_boot=True)
    maint = seed_mcp(services, owner, name="maint", port=9303, autostart_on_boot=True, maintenance=True)
    plain = seed_mcp(services, owner, name="plain", port=9304)
    mon = services.monitor
    for x in (kept, fresh, maint, plain): mon._prober.set_check(x.id, Issue.PROCESS_DOWN)
    engine = mon.engine(kept.id)
    mon.remove(fresh.id); mon.remove(maint.id); mon.remove(plain.id)
    await mon.start(run_loops=False); await mon.wait_idle()
    assert mon.engine(kept.id) is engine and mon._prober.check_calls == [fresh.id]
    assert [c.env["MCP_ID"] for c in mon._runner.calls] == [str(fresh.id)]
    assert mon.engine(maint.id).state == S.MAINTENANCE and mon.engine(plain.id).state == S.HEALTHY

async def test_round_errors_are_logged_and_loop_continues(services, monkeypatch):
    seed_mcp(services, make_user(services, "o@x.com")); mon = services.monitor
    services.settings.update({"ping_interval_sec": 1})
    real = mon.ping_round; n = 0
    async def flaky():
        nonlocal n; n += 1
        if n == 1: raise RuntimeError("round broke")
        await real()
    monkeypatch.setattr(mon, "ping_round", flaky)
    await mon.start(run_loops=True)
    await asyncio.sleep(1.3)
    assert n == 2 and len(mon._prober.probe_calls) == 1
    assert any("round broke" in e.get("error", "") for e in await logs(services, "system"))

async def test_housekeeping_flushes_and_purges_every_60th(services, monkeypatch):
    mon = services.monitor; seen = []
    monkeypatch.setattr(services.history, "flush", lambda: seen.append("flush"))
    monkeypatch.setattr(services.history, "purge", lambda: seen.append("purge") or 0)
    for _ in range(120): mon._housekeep()
    assert seen.count("flush") == 120 and seen.count("purge") == 2

async def test_stop_waits_for_short_script_and_closes(services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner); mon = services.monitor
    await mon.start(run_loops=True); loops = list(mon._loops)
    assert len(loops) == 4
    mon._runner.gate = asyncio.Event()
    mon.manual_action(m.id, "start", owner); await asyncio.sleep(0)
    asyncio.get_running_loop().call_later(0.2, mon._runner.gate.set)
    t = asyncio.get_running_loop().time()
    await mon.stop(grace_sec=5)
    assert asyncio.get_running_loop().time() - t < 2
    assert services.history.actions(m.id)[0].result.status == "ok" and mon._prober.closed
    assert all(task.cancelled() for task in loops) and mon._loops == []
    n = len(mon._prober.probe_calls); await asyncio.sleep(1.2)
    assert len(mon._prober.probe_calls) == n  # loops are gone
    await mon.stop()  # idempotent

async def test_stop_abandons_script_after_grace(services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner); mon = services.monitor
    mon._runner.gate = asyncio.Event()  # never set: the script outlives the grace period
    mon.manual_action(m.id, "start", owner); await asyncio.sleep(0)
    await mon.ping_round()
    t = asyncio.get_running_loop().time()
    await mon.stop(grace_sec=0.3)
    assert 0.25 < asyncio.get_running_loop().time() - t < 1.5
    assert services.history.actions(m.id) == [] and not mon._scripts and not mon._probes
    stop_ev = [e for e in await logs(services, "system") if e.get("event") == "monitor.stop"]
    assert stop_ev and stop_ev[-1]["abandoned"] == 1

async def test_stop_flushes_history(services):
    m = seed_mcp(services, make_user(services, "o@x.com")); mon = services.monitor
    await mon.ping_round(); await mon.wait_idle()
    await mon.stop()
    rows = services.db.query("SELECT ok, total FROM mcp_minutes WHERE mcp_id = ?", (m.id,))
    assert [(r["ok"], r["total"]) for r in rows] == [(1, 1)]


# ---- whole-plan review fixes (I1, I2, I3, M1, M6) ----

win_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


async def probes_idle(mon):
    """Wait for in-flight probes only (a gated script keeps running)."""
    while tasks := [t for t in mon._probes if not t.done()]:
        await asyncio.gather(*tasks, return_exceptions=True)


async def crash_gated(services, m):
    """crash_to_action without waiting for the (gated) script to finish."""
    mon = services.monitor; mon._prober.set_check(m.id, Issue.PROCESS_DOWN)
    await mon.issue_round(); await probes_idle(mon)
    services.clock.advance(30); await mon.confirm_round(); await probes_idle(mon)
    await asyncio.sleep(0)


async def test_single_action_task_across_maintenance_toggle(services):
    """I2: a hung auto start, maintenance on/off, checks failing past the delay -> still one runner call."""
    m = seed_mcp(services, make_user(services, "o@x.com")); mon = services.monitor
    mon._runner.gate = asyncio.Event()
    await crash_gated(services, m)
    assert len(mon._runner.calls) == 1
    first = mon._scripts[m.id]
    for on in (True, False):
        _, after = services.mcps.update(m.id, {"maintenance": on}); mon.reconfigure(after)
    for _ in range(4):
        await mon.issue_round(); await probes_idle(mon)
        services.clock.advance(30); await mon.confirm_round(); await probes_idle(mon)
    assert len(mon._runner.calls) == 1 and mon._scripts[m.id] is first and not first.done()
    with pytest.raises(ActionInProgressError): mon.remove(m.id)
    stop = asyncio.ensure_future(mon.stop(grace_sec=5)); await asyncio.sleep(0.05)
    assert not stop.done()  # stop() waits for the original task
    mon._runner.gate.set(); await stop
    assert first.done() and [a.kind for a in services.history.actions(m.id)] == ["start"]


async def test_apply_refuses_a_second_tracked_run(services):
    """I2 (defensive): _apply never replaces a tracked, unfinished script task."""
    from app.monitor.engine import RunScript
    m = seed_mcp(services, make_user(services, "o@x.com")); mon = services.monitor
    mon._runner.gate = asyncio.Event()
    await crash_gated(services, m)
    first = mon._scripts[m.id]
    mon._apply(m.id, [RunScript("restart", "auto", "UNRESPONSIVE")])
    await asyncio.sleep(0)
    assert mon._scripts[m.id] is first and len(mon._runner.calls) == 1
    refused = [e for e in await logs(services, "system") if e.get("event") == "monitor.action_refused"]
    assert refused and refused[0]["mcp_id"] == m.id and refused[0]["kind"] == "restart"
    mon._runner.gate.set(); await mon.wait_idle()


async def test_board_items_shared_across_subscribers_per_batch(services, monkeypatch):
    """I3: 100 subscribers x 50 changed MCPs -> at most one uptime() per MCP per batch."""
    from app.web.mcp_shared import board_stream
    owner = make_user(services, "o@x.com")
    ids = [seed_mcp(services, owner, name=f"m{i}", port=10000 + i).id for i in range(50)]
    gens = []
    for _ in range(100):
        sub = services.bus.subscribe()
        gen = board_stream(services.monitor, services.bus, sub, coalesce_sec=0, heartbeat_sec=30)
        await anext(gen)  # the initial board snapshot
        gens.append(gen)
    calls = []
    real = services.history.uptime
    monkeypatch.setattr(services.history, "uptime", lambda mcp_id, hours=24: calls.append(mcp_id) or real(mcp_id, hours))
    for _batch in range(2):
        calls.clear()
        for mcp_id in ids: services.bus.mark_dirty(mcp_id)
        for gen in gens:
            got = [json.loads((await anext(gen)).split("data: ", 1)[1])["id"] for _ in ids]
            assert got == ids
        assert sorted(calls) == ids  # once per MCP, shared by all 100 subscribers
    for gen in gens: await gen.aclose()


async def test_uptime_db_query_cached_per_minute(services, monkeypatch):
    """I3: the 24 h SUM runs once per MCP per minute bucket; flush, rollover and maintenance invalidate it."""
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner); mon = services.monitor
    h = services.history; queries = []
    real = services.db.query
    monkeypatch.setattr(services.db, "query", lambda sql, params=(): queries.append(sql) or real(sql, params))
    sums = lambda: sum("SUM(ok)" in q for q in queries)  # noqa: E731
    await mon.ping_round(); await mon.wait_idle()
    assert h.uptime(m.id) == 1.0 and h.uptime(m.id) == 1.0 and sums() == 1
    services.history.record(m.id, services.clock.now(), False, None)
    assert h.uptime(m.id) == 0.5 and sums() == 1  # unflushed counts are always live
    h.flush()
    assert h.uptime(m.id) == 0.5 and sums() == 2
    services.clock.advance(60)
    assert h.uptime(m.id) == 0.5 and sums() == 3
    assert h.uptime(m.id) == 0.5 and sums() == 3
    _, after = services.mcps.update(m.id, {"maintenance": True}); mon.reconfigure(after)
    assert h.uptime(m.id) == 0.5 and sums() == 4


async def test_script_hash_captured_inside_the_slot(services):
    """M1: an owner edit while the run waits for a slot runs the new script, with no tamper event."""
    if sys.platform != "win32": pytest.skip("Windows only")
    from app.monitor.runner import ScriptRunner
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner); mon = services.monitor
    services.scripts.put(m.id, "start", ScriptUpload(".bat", "exit /b 3"), owner.id)
    runner = mon._runner = ScriptRunner(concurrency=1)
    await runner._slots.acquire()  # every slot busy
    mon.manual_action(m.id, "start", owner)
    await asyncio.sleep(0.05)
    services.scripts.put(m.id, "start", ScriptUpload(".bat", "@echo off\necho new\nexit /b 0"), owner.id)
    runner._slots.release()
    await mon.wait_idle()
    a = services.history.actions(m.id)[0]
    assert (a.result.status, a.result.error, a.result.stdout.strip()) == ("ok", None, "new")
    assert await logs(services, "tamper") == []


@win_only
async def test_real_bat_gets_validated_name(services):
    """I1 regression: a Korean name with spaces reaches a .bat intact; an injected one cannot be stored."""
    from pydantic import ValidationError

    from app.monitor.runner import ScriptRunner
    try: "서울 날씨".encode("oem")
    except UnicodeEncodeError: pytest.skip("OEM code page cannot encode Korean")
    owner = make_user(services, "o@x.com")
    scripts = {"start": ScriptUpload(".bat", "@echo off\necho [%MCP_NAME%]\nexit /b 0"), "stop": ScriptUpload(".bat", "exit /b 0")}
    m = seed_mcp(services, owner, scripts=scripts, name="서울 날씨"); mon = services.monitor
    mon._runner = ScriptRunner()
    mon.manual_action(m.id, "start", owner); await mon.wait_idle()
    a = services.history.actions(m.id)[0]
    assert (a.result.status, a.result.stdout.strip()) == ("ok", "[서울 날씨]")
    with pytest.raises(ValidationError):
        services.mcps.update(m.id, {"name": "calc & echo INJECTED"})
    assert services.mcps.get(m.id).config.name == "서울 날씨"


async def test_start_skips_invalid_stored_config(services):
    """M6: one row the validator rejects is skipped (system event); every other MCP is monitored."""
    owner = make_user(services, "o@x.com")
    good = seed_mcp(services, owner); bad = seed_mcp(services, owner, name="legacy", port=9200)
    mon = services.monitor; mon.remove(good.id); mon.remove(bad.id)
    services.db.execute("UPDATE mcps SET config = json_set(config, '$.name', 'legacy & x') WHERE id = ?", (bad.id,))
    await mon.start(run_loops=False)
    assert mon.engine(good.id) is not None and mon.engine(bad.id) is None
    assert [i["id"] for i in mon.board()] == [good.id]
    await mon.ping_round(); await mon.wait_idle()
    assert mon._prober.probe_calls == [good.id]
    ev = [e for e in await logs(services, "system") if e.get("event") == "monitor.mcp_config_invalid"]
    assert len(ev) == 1 and ev[0]["mcp_id"] == bad.id and "name" in ev[0]["error"]
    bad_row = services.mcps.get(bad.id)
    assert bad_row.config_error and bad_row.config.name == "legacy & x"
    with pytest.raises(ValueError): mon.add(bad_row)
