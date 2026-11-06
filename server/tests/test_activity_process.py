import asyncio
import json
import threading
from datetime import timedelta

import pytest

from app.activity.context import ActivityContext
from app.activity.process import ProcessActivityHandler, ProcessComponent
from app.win.wmi import ProcessEvent
from tests.session_helpers import snap, ws
from tests.test_auth_api import audit_events
from tests.winfakes import FakeProcessSource, ListLog, eventually


def pev(kind="start", pid=8812, session=2, **kw):
    base = dict(kind=kind, at=kw.pop("at", None), pid=pid, ppid=4100, name="notepad.exe", exe=r"C:\Windows\notepad.exe",
                cmdline="notepad.exe a.txt", session_id=session, user="CORP\\hong", exit_code=None, source="wmi:poll")
    base.update(kw); return ProcessEvent(**base)

async def test_context_resolution_order(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2), ws(3, user="kim")))
    ctx = ActivityContext(services.rdp, clock, pid_session=lambda pid: {500: 3}.get(pid))
    ctx.remember(100, 2, "a.exe", clock.now())
    assert ctx.session_of(100) == 2 and ctx.session_of(500) == 3
    assert ctx.session_of(999, user="KIM", domain="CORP") == 3 and ctx.session_of(999) is None
    clock.advance(301); assert ctx.session_of(100) is None
    assert ctx.fields(2) == {"session_id": 2, "user": "CORP\\hong", "client_ip": "10.0.3.21", "client_name": "HONG-LAPTOP"}
    assert ctx.fields(None, user="X\\y") == {"session_id": None, "user": "X\\y", "client_ip": None, "client_name": None}

async def test_handler_logs_user_sessions_with_event_time(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    h = ProcessActivityHandler(ActivityContext(services.rdp, clock), services.log)
    at = clock.now() - timedelta(seconds=2)
    h([pev(at=at), pev(pid=9, session=0, at=at), pev("stop", at=clock.now(), exit_code=0, exe=None, cmdline=None)])
    lines = await audit_events(services, "activity.process")
    assert [(e["event"], e["pid"]) for e in lines] == [("start", 8812), ("stop", 8812)]
    s = lines[0]
    assert (s["ts"], s["cmdline"], s["session_id"], s["user"], s["client_ip"], s["source"]) == \
        ("2026-11-04T13:59:58.000+09:00", "notepad.exe a.txt", 2, "CORP\\hong", "10.0.3.21", "wmi:poll")
    assert "exit_code" not in s and lines[1]["exit_code"] == 0 and "cmdline" not in lines[1]

async def test_handler_resolves_missing_session_and_remembers(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    ctx = ActivityContext(services.rdp, clock, pid_session=lambda pid: 2)
    ProcessActivityHandler(ctx, services.log)([pev(session=None, at=clock.now())])
    assert ctx.session_of(8812) == 2 and (await audit_events(services, "activity.process"))[0]["session_id"] == 2

async def test_component_reports_mode_and_delivers(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    src = FakeProcessSource(start=[pev(at=clock.now())], mode="poll")
    comp = ProcessComponent(src, ProcessActivityHandler(ActivityContext(services.rdp, clock), services.log), services.collectors)
    services.collectors.add(comp); await services.collectors.start()
    try:
        await eventually(lambda: services.collectors.status() and services.collectors.status()[0].ok)
        await services.log.flush()
        await eventually(lambda: (services.paths.logs_dir / "2026-11-04.jsonl").exists()
                         and '"cat": "activity.process"' in (services.paths.logs_dir / "2026-11-04.jsonl").read_text("utf-8"))
    finally:
        await services.collectors.stop()
    modes = [e for e in await audit_events(services, "system") if e.get("event") == "collector.mode"]
    assert {(e["source"], e["mode"]) for e in modes} == {("wmi:start", "poll"), ("wmi:stop", "poll")}
    assert len(await audit_events(services, "activity.process")) == 1


# --- beyond the plan sketch ---------------------------------------------------------------------

async def test_context_lru_evicts_the_oldest_pid(services, clock):
    ctx = ActivityContext(services.rdp, clock, pid_session=lambda pid: None, max_pids=2)
    ctx.remember(1, 5, "a.exe", clock.now())
    ctx.remember(2, 6, "b.exe", clock.now())
    ctx.remember(1, 5, "a.exe", clock.now())  # 1 is now the newest
    ctx.remember(3, 7, "c.exe", clock.now())
    assert (ctx.session_of(1), ctx.session_of(2), ctx.session_of(3)) == (5, None, 7)


async def test_context_ttl_edge_and_unknown_cached_session_fall_through(services, clock):
    ctx = ActivityContext(services.rdp, clock, pid_session=lambda pid: 4)
    ctx.remember(1, 2, "a.exe", clock.now())
    ctx.remember(2, None, "b.exe", clock.now())
    clock.advance(300)
    assert ctx.session_of(1) == 2  # still inside ttl_sec
    assert ctx.session_of(2) == 4  # cached "unknown" does not hide ProcessIdToSessionId
    assert ctx.session_of(None) is None


async def test_context_by_user_needs_a_unique_session(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2), ws(3)))  # both sessions are CORP\hong
    ctx = ActivityContext(services.rdp, clock, pid_session=lambda pid: None)
    assert ctx.session_of(7, user="hong", domain="CORP") is None
    assert ctx.fields(9, user="CORP\\x") == {"session_id": 9, "user": "CORP\\x", "client_ip": None, "client_name": None}


async def test_handler_line_keys_follow_the_api_table(clock):
    log = ListLog()

    class NoSessions:
        def by_user(self, user, domain):
            return None

        def context(self, session_id):
            return None

    h = ProcessActivityHandler(ActivityContext(NoSessions(), clock, pid_session=lambda pid: None), log)
    h([pev(session=1, at=clock.now(), exe=None, ppid=None),
       pev("stop", session=None, at=clock.now(), exit_code=None, source="wmi:trace"),
       pev(pid=77, session=0, at=clock.now())])
    assert [(cat, at, sorted(f)) for cat, at, f in log.events] == [
        ("activity.process", clock.now(),
         sorted(["event", "pid", "ppid", "name", "cmdline", "source", "session_id", "user", "client_ip", "client_name"])),
        ("activity.process", clock.now(),
         sorted(["event", "pid", "ppid", "name", "source", "session_id", "user", "client_ip", "client_name"])),
    ]
    assert log.events[0][2]["ppid"] is None
    assert log.events[1][2]["session_id"] == 1  # the stop has no session: the start's cached one


async def test_component_retries_a_failed_watch_and_logs_mode_once(services, clock):
    src = FakeProcessSource(start=[RuntimeError("wmi gone"), pev(at=clock.now())], mode="trace")
    src.fail_watch("stop", OSError("denied"))
    comp = ProcessComponent(src, ProcessActivityHandler(ActivityContext(services.rdp, clock), services.log),
                            services.collectors, retry_sec=0.05)
    services.collectors.add(comp); await services.collectors.start()
    try:
        await eventually(lambda: src.watch_count("start") >= 2 and src.watch_count("stop") >= 2)
        await eventually(lambda: bool(services.collectors.status()) and services.collectors.status()[0].ok)
        await services.log.flush()
        await eventually(lambda: '"cat": "activity.process"' in
                         (services.paths.logs_dir / "2026-11-04.jsonl").read_text("utf-8"))
    finally:
        await services.collectors.stop()
    assert not [t for t in threading.enumerate() if t.name.startswith("wmi:")]
    assert all(w.closed for w in src.watches)
    system = await audit_events(services, "system")
    modes = [(e["source"], e["mode"]) for e in system if e.get("event") == "collector.mode"]
    assert sorted(modes) == [("wmi:start", "trace"), ("wmi:stop", "trace")]
    statuses = [(e["ok"], e["error"]) for e in system if e.get("event") == "collector.status"]
    assert (False, "OSError('denied')") in statuses or (False, "RuntimeError('wmi gone')") in statuses
    assert statuses[-1] == (True, None)


@pytest.mark.parametrize("with_process", [False, True])
async def test_build_services_wires_the_activity_context_and_wmi_component(tmp_path, clock, with_process):
    from app.collect.config import CollectorConfig
    from app.services import build_services
    from tests.fakes import CapturingOtpProvider, FakeProber, FakeRunner

    process = FakeProcessSource(start=[pev(session=1, at=clock.now())]) if with_process else None
    svc = build_services(tmp_path, clock=clock, otp_provider=CapturingOtpProvider(),
                         runner=FakeRunner(), prober=FakeProber(clock), collectors=CollectorConfig(process=process))
    assert isinstance(svc.activity_context, ActivityContext)
    await svc.log.start()
    try:
        await svc.collectors.start()
        try:
            if process is None:
                await asyncio.sleep(0.05)
                assert svc.collectors.status() == []
                assert not any(t.name.startswith("wmi:") for t in threading.enumerate())
            else:
                await eventually(lambda: [s.name for s in svc.collectors.status()] == ["wmi"])
                await eventually(lambda: svc.activity_context.session_of(8812) == 1)
        finally:
            await svc.collectors.stop()
    finally:
        await svc.log.stop()
        svc.db.close()


@pytest.mark.winlive
async def test_real_wmi_component_logs_a_process_start_and_stop(services):
    import subprocess

    from app.win.ffi import current_session_id
    from app.win.wmi import WmiProcessSource

    comp = ProcessComponent(WmiProcessSource(), ProcessActivityHandler(ActivityContext(services.rdp, services.clock),
                            services.log), services.collectors)
    services.collectors.add(comp); await services.collectors.start()
    try:
        await eventually(lambda: bool(services.collectors.status()) and services.collectors.status()[0].ok, timeout=15)
        await asyncio.sleep(1.5)  # both watchers have their queries in place
        p = subprocess.Popen(["ping", "-n", "3", "127.0.0.1"], stdout=subprocess.DEVNULL)
        await asyncio.to_thread(p.wait)

        def mine():  # lines go to the real event day's file, not the FakeClock day
            lines = [json.loads(x) for f in services.paths.logs_dir.glob("*.jsonl")
                     for x in f.read_text("utf-8").splitlines()]
            return [e for e in lines if e["cat"] == "activity.process" and e["pid"] == p.pid]

        async def both():
            await services.log.flush()
            return {e["event"] for e in mine()} == {"start", "stop"}

        for _ in range(100):
            if await both():
                break
            await asyncio.sleep(0.1)
    finally:
        await services.collectors.stop()
    got = {e["event"]: e for e in mine()}
    assert set(got) == {"start", "stop"}
    assert "ping" in got["start"]["cmdline"].lower() and got["start"]["session_id"] == current_session_id()
    assert got["start"]["source"] in ("wmi:trace", "wmi:poll") and got["start"]["user"]
    assert not [t for t in threading.enumerate() if t.name.startswith("wmi:")]
