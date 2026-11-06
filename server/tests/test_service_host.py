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
from app.winsvc.host import ServiceHost
from tests.fakes import FakeClock
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


def test_service_host_runs_until_stop(tmp_path):
    moved = []
    host = ServiceHost(_service_argv(tmp_path), chdir=moved.append)
    codes = []
    t = threading.Thread(target=lambda: codes.append(host.run())); t.start()
    assert host.control.wait_started(30)
    host.session_change(5, 2); host.stop(); t.join(30)
    assert codes == [0] and moved == [tmp_path.resolve()] and host.control.as_service
    lines = [json.loads(x) for f in sorted((tmp_path / "logs").glob("*.jsonl")) for x in f.read_text("utf-8").splitlines()]
    reconciled = [x for x in lines if x.get("event") == "service.start_type"]
    assert len(reconciled) == 1 and reconciled[0]["desired"] == "delayed-auto"
    assert reconciled[0]["result"] in ("applied", "in_sync", "not_installed", "denied", "error")


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
