import asyncio
import json
import socket
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

import app.main as main_mod
from app.collect.manager import Collectors
from app.db import MIGRATIONS, Database
from app.main import PortInUseError, ServeControl, bind_listener, serve
from app.paths import AppPaths
from app.rootlock import RootInUseError, RootLock
from app.winsvc.host import ServiceHost, StopHeartbeat, run_for_scm
from tests.fakes import FakeClock, FakeScm
from tests.live import free_port
from tests.winfakes import ListLog

SERVER_DIR = Path(__file__).resolve().parents[1]
NO_COLLECTORS = ("--session-source", "none")  # F08: never start the real WTS/event-log collectors


def run_app(*args, timeout=60):
    return subprocess.run([sys.executable, "-m", "app", *args], cwd=SERVER_DIR, capture_output=True, text=True,
                          timeout=timeout, stdin=subprocess.DEVNULL)


def test_busy_port_exits_3_without_traceback(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); s.listen(); busy = s.getsockname()[1]
        p = run_app("--root", str(tmp_path / "r"), "--local-port", str(busy), "--external-port", str(free_port()),
                    "--external-host", "127.0.0.1", *NO_COLLECTORS)
    assert p.returncode == 3 and f"port {busy} is already in use" in p.stderr and "Traceback" not in p.stderr
    assert not (tmp_path / "r" / "data" / "config.db").exists()


def test_newer_database_exits_5(tmp_path):
    AppPaths(tmp_path).ensure()
    db = Database(AppPaths(tmp_path).db_path); db.migrate()
    db.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 3}"); db.close()
    p = run_app("--root", str(tmp_path), "--local-port", str(free_port()), "--external-port", str(free_port()),
                "--external-host", "127.0.0.1", *NO_COLLECTORS)
    assert p.returncode == 5 and "written by a newer version" in p.stderr and "Traceback" not in p.stderr
    assert f"{tmp_path.resolve() / 'data' / 'config.db'} was written" in p.stderr
    assert f"(schema {len(MIGRATIONS) + 3} > {len(MIGRATIONS)})" in p.stderr


def test_root_in_use_exits_4(tmp_path):
    AppPaths(tmp_path).ensure()
    with RootLock(tmp_path):
        p = run_app("--root", str(tmp_path), "--local-port", str(free_port()), "--external-port", str(free_port()),
                    "--external-host", "127.0.0.1", *NO_COLLECTORS)
    assert p.returncode == 4 and "already in use by another MCP Monitor process" in p.stderr
    assert "Traceback" not in p.stderr


def test_reindex_refuses_a_root_in_use(tmp_path):
    AppPaths(tmp_path).ensure()
    with RootLock(tmp_path):
        p = run_app("reindex", "--root", str(tmp_path))
    assert p.returncode == 4 and "already in use by another MCP Monitor process" in p.stderr
    assert "Traceback" not in p.stderr


def test_version_flag():
    p = run_app("--version")
    assert p.returncode == 0 and p.stdout.strip() == "mcp-monitor 1.0.0"


def test_service_mode_from_a_console_exits_2():
    p = run_app("service")
    assert p.returncode == 2 and "must be started by the Service Control Manager" in p.stderr
    assert "Traceback" not in p.stderr


def test_root_lock_is_exclusive_and_released(tmp_path):
    with RootLock(tmp_path):
        assert (tmp_path / "data" / ".lock").is_file()
        with pytest.raises(RootInUseError):
            RootLock(tmp_path).acquire()
    with RootLock(tmp_path):  # released: a new holder gets it
        pass


def test_bind_listener_reports_the_busy_port():
    first = bind_listener("127.0.0.1", 0)
    port = first.getsockname()[1]
    try:
        with pytest.raises(PortInUseError) as e:
            bind_listener("127.0.0.1", port)
    finally:
        first.close()
    assert (e.value.host, e.value.port) == ("127.0.0.1", port) and isinstance(e.value, OSError)
    assert str(e.value) == f"port {port} is already in use (127.0.0.1)"


def test_serve_control_stops_from_another_thread(tmp_path):
    ctrl = ServeControl()
    t = threading.Thread(target=lambda: asyncio.run(serve(tmp_path, free_port(), free_port(), external_host="127.0.0.1",
                                                          control=ctrl)))
    t.start()
    assert ctrl.wait_started(30)
    ctrl.nudge_sessions()  # no session collection configured: a no-op
    ctrl.request_stop(); ctrl.request_stop(); t.join(30)  # a repeated request is harmless
    assert not t.is_alive() and ctrl.wait_stopped(0)


def test_request_stop_before_start_still_stops(tmp_path):
    ctrl = ServeControl(); ctrl.request_stop()
    t = threading.Thread(target=lambda: asyncio.run(serve(tmp_path, free_port(), free_port(), external_host="127.0.0.1",
                                                          control=ctrl)))
    t.start(); t.join(30)
    assert not t.is_alive() and ctrl.wait_stopped(0)


def _answers(port: int) -> bool:
    try:
        return httpx.get(f"http://127.0.0.1:{port}/api/bootstrap", timeout=5).status_code == 200
    except httpx.HTTPError:
        return False


def test_serve_control_stop_runs_the_collectors_stop_first(tmp_path, monkeypatch):
    """F01: a service stop goes through ShutdownSequence: the collectors stop while the Local
    channel still answers (agents hear ``exit``), then the servers, then the monitor."""
    lp, ep = free_port(), free_port()
    order = []
    real_build = main_mod.build_services

    def build(root, **kw):
        services = real_build(root, **kw)
        collectors_stop, monitor_stop = services.collectors.stop, services.monitor.stop

        async def stop_collectors():
            if not order:  # the sequence's call (serve() calls it again as a no-op later)
                order.append(("collectors.stop", await asyncio.to_thread(_answers, lp)))
            await collectors_stop()

        async def stop_monitor(*a, **k):
            order.append(("monitor.stop", await asyncio.to_thread(_answers, lp), k))
            await monitor_stop(*a, **k)

        services.collectors.stop = stop_collectors
        services.monitor.stop = stop_monitor
        return services

    monkeypatch.setattr(main_mod, "build_services", build)
    ctrl = ServeControl()
    t = threading.Thread(target=lambda: asyncio.run(serve(tmp_path, lp, ep, external_host="127.0.0.1", control=ctrl)))
    t.start()
    assert ctrl.wait_started(30)
    threading.Thread(target=ctrl.request_stop).start()
    t.join(30)
    assert not t.is_alive()
    assert order == [("collectors.stop", True), ("monitor.stop", False, {"kill_abandoned": True})]


def test_serve_passes_kill_scripts_on_stop_to_the_monitor(tmp_path, monkeypatch):
    seen = []
    real_build = main_mod.build_services

    def build(root, **kw):
        services = real_build(root, **kw)
        monitor_stop = services.monitor.stop

        async def stop_monitor(*a, **k):
            seen.append(k)
            await monitor_stop(*a, **k)

        services.monitor.stop = stop_monitor
        return services

    monkeypatch.setattr(main_mod, "build_services", build)
    ctrl = ServeControl(); ctrl.request_stop()
    asyncio.run(serve(tmp_path, free_port(), free_port(), external_host="127.0.0.1", control=ctrl,
                      kill_scripts_on_stop=False))
    assert seen == [{"kill_abandoned": False}]


def test_serve_releases_the_root_lock_and_the_ports(tmp_path):
    lp, ep = free_port(), free_port()
    ctrl = ServeControl(); ctrl.request_stop()
    asyncio.run(serve(tmp_path, lp, ep, external_host="127.0.0.1", control=ctrl))
    with RootLock(tmp_path):
        pass
    bind_listener("127.0.0.1", lp).close()
    bind_listener("127.0.0.1", ep).close()


def test_serve_in_use_root_leaves_the_ports_free(tmp_path):
    lp, ep = free_port(), free_port()
    with RootLock(tmp_path), pytest.raises(RootInUseError):
        asyncio.run(serve(tmp_path, lp, ep, external_host="127.0.0.1"))
    bind_listener("127.0.0.1", lp).close()
    bind_listener("127.0.0.1", ep).close()
    assert not (tmp_path / "data" / "config.db").exists()


def _service_argv(tmp_path, local_port=None):
    return ["--root", str(tmp_path), "--local-port", str(local_port or free_port()),
            "--external-port", str(free_port()), "--external-host", "127.0.0.1", *NO_COLLECTORS]


def _log_lines(root):
    return [json.loads(x) for f in sorted((root / "logs").glob("*.jsonl")) for x in f.read_text("utf-8").splitlines()]


@pytest.mark.parametrize("start,result,applied", [("delayed-auto", "in_sync", []), ("manual", "applied", ["delayed-auto"])])
def test_service_host_runs_until_stop(tmp_path, start, result, applied):
    # plan review minor 10: a fake SCM, never the installed service (an elevated run would change it)
    moved = []
    scm = FakeScm(start=start)
    host = ServiceHost(_service_argv(tmp_path), chdir=moved.append, configurator=scm)
    codes = []
    t = threading.Thread(target=lambda: codes.append(host.run())); t.start()
    assert host.control.wait_started(30)
    host.session_change(5, 2); host.stop(); t.join(30)
    assert codes == [0] and moved == [tmp_path.resolve()] and host.control.as_service
    reconciled = [x for x in _log_lines(tmp_path) if x.get("event") == "service.start_type"]
    assert [(x["result"], x["desired"], x["current"]) for x in reconciled] == [(result, "delayed-auto", start)]
    assert scm.applied == applied


def test_run_for_scm_reports_stopped_after_any_requested_stop():
    # plan review I4: after an SCM stop, a failing shutdown still ends with SERVICE_STOPPED (None)
    errors = []
    requested = threading.Event(); requested.set()

    def boom():
        raise RuntimeError("collectors stop failed")

    assert run_for_scm(boom, requested, errors.append) is None
    assert "RuntimeError: collectors stop failed" in errors[0] and "code 1" in errors[1]
    errors.clear()
    assert run_for_scm(lambda: 0, requested, errors.append) is None and errors == []
    assert run_for_scm(lambda: 4, requested, errors.append) is None and errors == ["mcp-monitor stopped on request with errors (code 4)"]


def test_run_for_scm_leaves_for_recovery_when_it_ends_on_its_own():
    errors = []
    idle = threading.Event()
    assert run_for_scm(lambda: 3, idle, errors.append) == 3
    assert run_for_scm(lambda: 0, idle, errors.append) == 1  # ending without a stop request is a failure
    assert run_for_scm(lambda: 1 / 0, idle, errors.append) == 1
    assert errors[:2] == ["mcp-monitor exited with code 3", "mcp-monitor exited with code 0"]
    assert "ZeroDivisionError" in errors[2]


def test_a_failing_stop_sequence_under_the_service_still_reports_stopped(tmp_path, monkeypatch):
    """I4 end to end: the real server; the collectors' stop raises during the SCM-requested stop."""
    real_build = main_mod.build_services

    def build(root, **kw):
        services = real_build(root, **kw)
        real_stop = services.collectors.stop
        calls = []

        async def failing_stop():
            calls.append(1)
            await real_stop()
            if len(calls) == 1:
                raise RuntimeError("taskkill failed")

        services.collectors.stop = failing_stop
        return services

    monkeypatch.setattr(main_mod, "build_services", build)
    host = ServiceHost(_service_argv(tmp_path), chdir=lambda p: None, configurator=FakeScm())
    requested, errors, outcome = threading.Event(), [], []
    t = threading.Thread(target=lambda: outcome.append(run_for_scm(host.run, requested, errors.append)))
    t.start()
    assert host.control.wait_started(30)
    requested.set(); host.stop(); t.join(60)
    assert not t.is_alive() and outcome == [None]
    assert "RuntimeError: taskkill failed" in errors[0]
    # the trail before the failure is on disk (the log was flushed and stopped in order)
    assert any(x.get("event") == "service.start_type" for x in _log_lines(tmp_path))


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class _Done:
    """A ``threading.Event`` stand-in: ``wait`` advances the fake clock instead of sleeping."""

    def __init__(self, clock, done_after=None):
        self.clock, self.done_after, self.waits = clock, done_after, 0

    def wait(self, timeout):
        self.waits += 1
        self.clock.t += timeout
        return self.done_after is not None and self.waits > self.done_after


def test_stop_heartbeat_reports_until_the_run_ends():
    clock, reports, gave_up = _Clock(), [], []
    StopHeartbeat(lambda: reports.append(clock.t), _Done(clock, done_after=3), lambda: gave_up.append(1),
                  interval=2, deadline=50, clock=clock).run()
    assert reports == [2, 4, 6] and gave_up == []


def test_stop_heartbeat_gives_up_at_the_deadline():
    clock, reports, gave_up = _Clock(), [], []
    StopHeartbeat(lambda: reports.append(clock.t), _Done(clock), lambda: gave_up.append(clock.t),
                  interval=2, deadline=10, clock=clock).run()
    assert reports == [2, 4, 6, 8] and gave_up == [10]


def test_stop_budget_fits_the_preshutdown_timeout():
    from app.winsvc import (
        PRESHUTDOWN_TIMEOUT_MS,
        STOP_DEADLINE_SEC,
        STOP_HEARTBEAT_SEC,
        STOP_WAIT_HINT_MS,
    )
    assert STOP_HEARTBEAT_SEC * 1000 < STOP_WAIT_HINT_MS  # each report promises the next in time
    assert STOP_DEADLINE_SEC * 1000 + STOP_WAIT_HINT_MS <= PRESHUTDOWN_TIMEOUT_MS


def test_service_host_reports_a_busy_port(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); s.listen()
        host = ServiceHost(_service_argv(tmp_path, s.getsockname()[1]), chdir=lambda p: None)
        assert host.run() == 3


def test_service_host_reports_bad_arguments_as_2(tmp_path):
    host = ServiceHost(["--local-port", "not-a-port"], chdir=lambda p: None)
    assert host.run() == 2


def test_service_class_contract():
    from app.winsvc import service
    assert service.McpMonitorService._svc_name_ == "mcp-monitor"
    assert service.McpMonitorService._svc_display_name_ == "MCP Monitor"
    assert callable(service.McpMonitorService.SvcOtherEx) and callable(service.dispatch)


class _FakeHost:
    def __init__(self, run):
        self._run, self.stops, self.nudges = run, 0, []
        self.stopped = threading.Event()

    def run(self):
        return self._run(self)

    def stop(self):
        self.stops += 1
        self.stopped.set()

    def session_change(self, event_type, session_id):
        self.nudges.append((event_type, session_id))


def _service(monkeypatch, run):
    """A McpMonitorService without the SCM: statuses recorded, event log / exit / SCM config faked."""
    import win32service

    from app.winsvc import service
    svc = object.__new__(service.McpMonitorService)
    svc._setup(_FakeHost(run))
    svc.statuses, svc.errors, svc.exits, svc.preshutdown = [], [], [], []
    svc.ssh, svc.checkPoint = object(), 0  # the framework's own ReportServiceStatus, SetServiceStatus faked
    # (state, checkpoint, wait hint) of every SetServiceStatus
    monkeypatch.setattr(win32service, "SetServiceStatus", lambda ssh, st: svc.statuses.append((st[1], st[5], st[6])))
    monkeypatch.setattr(service, "_log_error", svc.errors.append)
    monkeypatch.setattr(service, "_log_warning", svc.errors.append)
    monkeypatch.setattr(service, "_set_preshutdown_timeout", lambda: svc.preshutdown.append(1))

    def fake_exit(code):
        svc.exits.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(service, "_exit", fake_exit)
    return svc, win32service


def test_service_accepts_preshutdown_and_stops_once(monkeypatch):
    svc, ws = _service(monkeypatch, lambda h: 0)
    accepted = svc.GetAcceptedControls()
    for flag in (ws.SERVICE_ACCEPT_STOP, ws.SERVICE_ACCEPT_SHUTDOWN, ws.SERVICE_ACCEPT_SESSIONCHANGE, ws.SERVICE_ACCEPT_PRESHUTDOWN):
        assert accepted & flag, flag
    svc.SvcOtherEx(ws.SERVICE_CONTROL_SESSIONCHANGE, 5, (3,))
    svc.SvcOtherEx(ws.SERVICE_CONTROL_PRESHUTDOWN, 0, None)
    svc.SvcShutdown(); svc.SvcStop()  # SHUTDOWN after PRESHUTDOWN, a second stop: one sequence
    svc._run_done.set()
    assert svc.host.nudges == [(5, 3)] and svc.host.stops == 1
    assert svc.statuses[0] == (ws.SERVICE_STOP_PENDING, 1, 10_000)


def test_service_stop_error_reports_stopped_not_a_crash(monkeypatch):
    # plan review I4: the stop sequence raises after an SCM stop -> SvcDoRun returns (the framework
    # reports STOPPED), no os._exit (which the SCM would treat as a crash and restart)
    def run(host):
        assert host.stopped.wait(10)
        raise RuntimeError("monitor kill failed")

    svc, ws = _service(monkeypatch, run)
    threading.Timer(0.2, svc.SvcStop).start()
    svc.SvcRun()
    assert svc.exits == [] and svc.preshutdown == [1] and svc._run_done.is_set()
    assert svc.statuses[:2] == [(ws.SERVICE_RUNNING, 0, 5000), (ws.SERVICE_STOP_PENDING, 1, 10_000)]
    assert ws.SERVICE_STOPPED not in [s for s, _c, _w in svc.statuses]  # the framework reports it after SvcRun
    assert any("monitor kill failed" in e for e in svc.errors)


def test_heartbeat_never_reports_stop_pending_after_the_run_ended(monkeypatch):
    # re-review 6: the heartbeat's wait timed out just before the run ended; its late tick must not reach
    # the SCM after the framework's STOPPED (the process would then leave in STOP_PENDING: a crash)
    from app.winsvc import service
    beats = []

    class _Beat:
        def __init__(self, report, done, give_up):
            beats.append(report)

        def start(self):
            pass

    monkeypatch.setattr(service, "StopHeartbeat", _Beat)

    def run(host):
        assert host.stopped.wait(10)
        return 0

    svc, ws = _service(monkeypatch, run)
    locked = []

    class _Done(threading.Event):
        def set(self):
            locked.append(svc._status_lock.locked())  # set while no report is half-way through
            super().set()

    svc._run_done = _Done()
    threading.Timer(0.1, svc.SvcStop).start()
    svc.SvcRun()  # returns: the framework's C side reports STOPPED now
    reported = list(svc.statuses)
    beats[0]()  # the heartbeat thread's late tick
    assert svc.statuses == reported and reported[-1][0] == ws.SERVICE_STOP_PENDING
    assert locked == [True]


def test_service_that_ends_on_its_own_exits_for_recovery(monkeypatch):
    svc, _ws = _service(monkeypatch, lambda h: 3)
    with pytest.raises(SystemExit):
        svc.SvcRun()
    assert svc.exits == [3] and svc.errors == ["mcp-monitor exited with code 3"]


def test_service_heartbeat_reports_progress_and_gives_up(monkeypatch):
    import app.winsvc.host as host_mod
    from app.winsvc import service
    monkeypatch.setattr(host_mod, "STOP_HEARTBEAT_SEC", 0.01)
    svc, ws = _service(monkeypatch, lambda h: 0)
    monkeypatch.setattr(service, "StopHeartbeat",
                        lambda report, done, give_up: host_mod.StopHeartbeat(report, done, give_up, interval=0.01, deadline=0.2))
    gave_up = threading.Event()
    real_give_up = svc._give_up

    def give_up():
        try:
            real_give_up()
        except SystemExit:
            gave_up.set()

    svc._give_up = give_up
    svc.SvcStop()
    assert gave_up.wait(10)
    checkpoints = [c for s, c, w in svc.statuses if s == ws.SERVICE_STOP_PENDING and w == 10_000]
    assert len(checkpoints) >= 3 and checkpoints == list(range(1, len(checkpoints) + 1))  # increasing
    assert svc.statuses[-1][0] == ws.SERVICE_STOPPED and svc.exits == [0]
    assert "did not stop within" in svc.errors[0]


class _Nudged:
    name = "wts"

    def __init__(self):
        self.nudges = 0

    def start(self, bridge):
        pass

    def stop(self):
        pass

    def nudge(self):
        self.nudges += 1


class _Plain:
    name = "plain"

    def start(self, bridge):
        pass

    def stop(self):
        pass


def test_collectors_nudge_sessions_reaches_components_with_nudge():
    collectors = Collectors(ListLog(), FakeClock(datetime(2026, 11, 4, tzinfo=UTC)))
    nudged = _Nudged()
    collectors.add(_Plain()); collectors.add(nudged)
    collectors.nudge_sessions()
    assert nudged.nudges == 1


def test_build_services_closes_the_database_when_wiring_fails(tmp_path, monkeypatch):
    import app.services as services_mod

    def broken(*a, **k):
        raise RuntimeError("wiring failed")

    monkeypatch.setattr(services_mod, "McpStore", broken)
    with pytest.raises(RuntimeError, match="wiring failed"):
        services_mod.build_services(tmp_path)
    (tmp_path / "data" / "config.db").unlink()  # Windows refuses to delete a file that is still open


def test_build_services_closes_a_newer_database(tmp_path):
    import app.services as services_mod
    from app.db import DatabaseTooNewError

    AppPaths(tmp_path).ensure()
    db = Database(AppPaths(tmp_path).db_path); db.migrate()
    db.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}"); db.close()
    with pytest.raises(DatabaseTooNewError):
        services_mod.build_services(tmp_path)
    (tmp_path / "data" / "config.db").unlink()
