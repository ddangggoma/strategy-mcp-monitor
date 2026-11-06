import asyncio
import socket
import threading
import time
from datetime import timedelta

import pytest

from app.collect.bridge import CollectorBridge
from app.collect.config import CollectorConfig
from app.collect.manager import Collectors, SessionsComponent
from app.services import build_services
from app.sessions.collector import SessionCollector, WtsFailure
from app.sessions.rdns import ReverseDns
from app.web.mcp_shared import board_snapshot
from app.win.wts import WtsError, WtsSnapshot
from tests.fakes import CapturingOtpProvider, FakeProber, FakeRunner
from tests.session_helpers import snap, ws
from tests.test_auth_api import audit_events
from tests.winfakes import FakeWtsSource, ListLog, eventually


async def test_collector_posts_snapshots_and_failures(clock):
    got = []; bridge = CollectorBridge(asyncio.get_running_loop(), ListLog())
    src = FakeWtsSource([snap(clock.now()), WtsError("rpc"), snap(clock.now(), ws(2))])
    c = SessionCollector(src, bridge.register("wts", got.extend), clock, interval_sec=0.01); c.start()
    try:
        await eventually(lambda: len(got) >= 3)
    finally:
        c.stop()
    assert [type(x) for x in got[:3]] == [WtsSnapshot, WtsFailure, WtsSnapshot] and got[1].error == "WtsError('rpc')"


async def test_nudge_wakes_the_collector_early(clock):
    got = []; bridge = CollectorBridge(asyncio.get_running_loop(), ListLog())
    c = SessionCollector(FakeWtsSource([snap(clock.now())]), bridge.register("wts", got.extend), clock, interval_sec=30); c.start()
    try:
        await eventually(lambda: len(got) == 1)
        c.nudge()
        await eventually(lambda: len(got) == 2, timeout=1.0)
    finally:
        c.stop()


async def test_stop_joins_quickly(clock):
    c = SessionCollector(FakeWtsSource([snap(clock.now())]), lambda item: None, clock, interval_sec=30); c.start()
    t0 = time.monotonic(); c.stop()
    assert not c.alive and time.monotonic() - t0 < 2.0


async def test_reverse_dns_timeout_cache_and_errors(clock):
    def slow(ip):
        time.sleep(0.5); return ("late.corp", [], [ip])
    assert await ReverseDns(slow, timeout_sec=0.05, clock=clock).resolve("10.0.3.21") is None
    calls = []
    def fast(ip):
        calls.append(ip)
        if ip == "10.0.0.2":
            raise socket.herror(1, "unknown host")
        return ("pc.corp", [], [ip])
    r = ReverseDns(fast, timeout_sec=1, clock=clock)
    assert await r.resolve("10.0.0.1") == "pc.corp" and await r.resolve("10.0.0.1") == "pc.corp"
    assert await r.resolve("10.0.0.2") is None and await r.resolve("10.0.0.2") is None
    assert calls == ["10.0.0.1", "10.0.0.2"] and await r.resolve("not-an-ip") is None
    clock.advance(601); await r.resolve("10.0.0.1"); assert calls.count("10.0.0.1") == 2


# ---- beyond the plan's list ---------------------------------------------------------


async def test_reverse_dns_timeout_is_not_cached(clock):
    calls = []
    def lookup(ip):
        calls.append(ip)
        if len(calls) == 1:
            time.sleep(0.3)
        return ("pc.corp", [], [ip])
    r = ReverseDns(lookup, timeout_sec=0.1, clock=clock)
    assert await r.resolve("10.0.0.1") is None
    assert await r.resolve("10.0.0.1") == "pc.corp" and len(calls) == 2


async def test_any_source_exception_is_posted_as_a_failure(clock):
    got = []; bridge = CollectorBridge(asyncio.get_running_loop(), ListLog())
    c = SessionCollector(FakeWtsSource([ValueError("bad")]), bridge.register("wts", got.extend), clock, interval_sec=0.01)
    c.start()
    try:
        await eventually(lambda: len(got) >= 2)
    finally:
        c.stop()
    assert got[0] == WtsFailure("ValueError('bad')", clock.now())


async def test_collector_thread_is_a_named_daemon(clock):
    c = SessionCollector(FakeWtsSource([snap(clock.now())]), lambda item: None, clock, interval_sec=30); c.start()
    try:
        [t] = [t for t in threading.enumerate() if t.name == "wts-collector"]
        assert t.daemon and c.alive
    finally:
        c.stop()
    assert not any(t.name == "wts-collector" for t in threading.enumerate())


class _Recorder:
    """A Component that records what happened to it (and can fail on start)."""

    def __init__(self, name, fail=False):
        self.name, self.fail, self.calls = name, fail, []

    def start(self, bridge):
        self.calls.append(("start", threading.current_thread() is threading.main_thread()))
        if self.fail:
            raise RuntimeError("no access")

    def stop(self):
        self.calls.append(("stop", threading.current_thread() is threading.main_thread()))


async def test_collectors_start_report_failures_and_stop(services, clock):
    cs = Collectors(services.log, clock)
    good, bad = _Recorder("b-good"), _Recorder("a-bad", fail=True)
    cs.add(good); cs.add(bad)
    ran = asyncio.Event(); cancelled = []
    async def task():
        ran.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.append(True); raise
    cs.add_task("ticker", task)
    await cs.start()
    await asyncio.wait_for(ran.wait(), 1)
    assert cs.bridge is not None and good.calls == [("start", True)]
    assert [(s.name, s.ok, s.error) for s in cs.status()] == [("a-bad", False, "RuntimeError('no access')")]
    await cs.stop()
    assert cancelled == [True]
    assert good.calls[-1] == ("stop", False) and bad.calls[-1] == ("stop", False)  # stop runs in a worker thread
    events = [e for e in await audit_events(services, "system") if e["event"] == "collector.status"]
    assert [(e["source"], e["ok"], e["error"]) for e in events] == [("a-bad", False, "RuntimeError('no access')")]


async def test_task_stop_hooks_run_first_in_reverse_order_while_tasks_still_run(services, clock):
    """F07: a task's graceful ``stop`` is awaited before any task is cancelled or component stopped."""
    cs = Collectors(services.log, clock)
    comp = _Recorder("comp"); cs.add(comp)
    order = []
    running = {"one": False, "two": False, "plain": False}

    def job(name):
        async def run():
            running[name] = True
            try:
                await asyncio.sleep(3600)
            finally:
                running[name] = False
        return run

    def hook(name, fail=False):
        async def stop():
            order.append((name, dict(running), len(comp.calls)))
            if fail:
                raise RuntimeError("stuck")
        return stop

    cs.add_task("one", job("one"), stop=hook("one", fail=True))
    cs.add_task("two", job("two"), stop=hook("two"))
    cs.add_task("plain", job("plain"))
    await cs.stop()  # never started: no hooks
    assert order == []
    await cs.start()
    await asyncio.sleep(0)
    await cs.stop()
    everything_running = {"one": True, "two": True, "plain": True}
    assert order == [("two", everything_running, 1), ("one", everything_running, 1)]
    assert not any(running.values()) and comp.calls[-1] == ("stop", False)
    [status] = cs.status()
    assert (status.name, status.ok, status.error) == ("one", False, "stop failed: RuntimeError('stuck')")


async def test_report_updates_since_and_logs_only_on_change(services, clock):
    cs = Collectors(services.log, clock)
    t0 = clock.now()
    cs.report("wts", True); clock.advance(5); cs.report("wts", True)
    assert [(s.name, s.ok, s.error, s.since) for s in cs.status()] == [("wts", True, None, t0)]
    clock.advance(5); cs.report("wts", False, "denied"); clock.advance(5); cs.report("wts", False, "denied")
    t1 = clock.now() - timedelta(seconds=5)
    cs.report("eventlog", True)
    assert [(s.name, s.ok, s.error, s.since) for s in cs.status()] == [
        ("eventlog", True, None, clock.now()), ("wts", False, "denied", t1)]
    events = [e for e in await audit_events(services, "system") if e["event"] == "collector.status"]
    assert [(e["source"], e["ok"], e["error"]) for e in events] == [
        ("wts", True, None), ("wts", False, "denied"), ("eventlog", True, None)]


async def test_sessions_component_feeds_the_tracker_and_resolves_dns(services, clock):
    lookups = []
    def lookup(ip):
        lookups.append(ip); return ("hong-pc.corp", [], [ip])
    src = FakeWtsSource([snap(clock.now(), ws(2)), WtsError("rpc"), snap(clock.now(), ws(2))])
    cs = services.collectors
    comp = SessionsComponent(src, services.rdp, cs, ReverseDns(lookup, clock=clock), clock, interval_sec=0.01)
    cs.add(comp)
    await cs.start()
    try:
        await eventually(lambda: services.rdp.ready and src.calls >= 3)
        await eventually(lambda: (services.rdp.board_sessions() or [{}])[0].get("reverse_dns") == "hong-pc.corp")
        assert [(s.name, s.ok) for s in cs.status()] == [("wts", True)]
    finally:
        await cs.stop()
    assert lookups == ["10.0.3.21"] and not comp.alive
    [conn] = services.rdp_history.connections(clock.now() - timedelta(days=1))
    assert conn.kind == "existing" and conn.reverse_dns == "hong-pc.corp"
    system = await audit_events(services, "system")
    assert [(e["ok"], e["error"]) for e in system if e["event"] == "collector.status"] == [
        (True, None), (False, "WtsError('rpc')"), (True, None)]
    assert [e["error"] for e in system if e["event"] == "sessions.wts_failed"] == ["WtsError('rpc')"]


async def test_sessions_component_logs_an_unexpected_resolver_error(services, clock):
    def broken(ip):
        raise UnicodeError("idna")
    comp = SessionsComponent(FakeWtsSource([snap(clock.now(), ws(2))]), services.rdp, services.collectors,
                             ReverseDns(broken, clock=clock), clock, interval_sec=30)
    services.collectors.add(comp)
    await services.collectors.start()
    try:
        await eventually(lambda: services.rdp.ready)
        await asyncio.sleep(0.1)
        failed = [e for e in await audit_events(services, "system") if e["event"] == "collector.handler_failed"]
        assert [(e["source"], e["error"]) for e in failed] == [("wts:rdns", "UnicodeError('idna')")]
    finally:
        await services.collectors.stop()
    assert services.rdp.board_sessions()[0]["reverse_dns"] is None


async def test_sessions_component_closes_dangling_connections_on_start(services, clock):
    services.rdp_history.open(ws(2), "logon", clock.now())  # a previous run's open connection
    tracker = services.rdp
    comp = SessionsComponent(FakeWtsSource([snap(clock.now())]), tracker, services.collectors,
                             ReverseDns(lambda ip: ("x", [], [ip]), clock=clock), clock, interval_sec=30)
    services.collectors.add(comp)
    await services.collectors.start()
    try:
        await eventually(lambda: tracker.ready)
    finally:
        await services.collectors.stop()
    [conn] = services.rdp_history.connections(clock.now() - timedelta(days=1))
    assert conn.end_reason == "service_stop"


async def test_sessions_component_closes_pending_displays_before_the_first_snapshot(services, clock):
    old = services.displays.create(services.rdp_history.open(ws(2), "logon", clock.now()))  # a previous run's
    comp = SessionsComponent(FakeWtsSource([snap(clock.now(), ws(2))]), services.rdp, services.collectors,
                             ReverseDns(lambda ip: ("x", [], [ip]), clock=clock), clock, interval_sec=30,
                             displays=services.displays)
    services.collectors.add(comp)
    await services.collectors.start()
    try:
        await eventually(lambda: services.rdp.ready)
    finally:
        await services.collectors.stop()
    assert services.displays.get(old.id).closed_reason == "service_restart"
    new = services.displays.pending_for_session(2)
    assert new.id != old.id and new.kind == "existing"
    notice = await audit_events(services, "notice")
    assert [(e["display_id"], e["reason"]) for e in notice] == [(old.id, "service_restart")]


async def test_sessions_component_nudge_reaches_the_collector(services, clock):
    src = FakeWtsSource([snap(clock.now())])
    comp = SessionsComponent(src, services.rdp, services.collectors,
                             ReverseDns(lambda ip: ("x", [], [ip]), clock=clock), clock, interval_sec=30)
    services.collectors.add(comp)
    await services.collectors.start()
    try:
        await eventually(lambda: src.calls == 1)
        comp.nudge()
        await eventually(lambda: src.calls == 2, timeout=1.0)
    finally:
        await services.collectors.stop()


@pytest.mark.parametrize("wts", [False, True])
async def test_build_services_adds_the_sessions_component_only_with_a_source(tmp_path, clock, wts):
    cfg = CollectorConfig(wts=FakeWtsSource([snap(clock.now(), ws(2))]) if wts else None, poll_interval_sec=0.01)
    svc = build_services(tmp_path, clock=clock, otp_provider=CapturingOtpProvider(),
                         runner=FakeRunner(), prober=FakeProber(clock), collectors=cfg)
    await svc.log.start()
    try:
        await svc.collectors.start()
        try:
            if wts:
                await eventually(lambda: "sessions" in board_snapshot(svc))
                assert any(t.name == "wts-collector" for t in threading.enumerate())
            else:
                await asyncio.sleep(0.05)
                assert "sessions" not in board_snapshot(svc) and svc.collectors.status() == []
                assert not any(t.name == "wts-collector" for t in threading.enumerate())
        finally:
            await svc.collectors.stop()
    finally:
        await svc.log.stop()
        svc.db.close()
