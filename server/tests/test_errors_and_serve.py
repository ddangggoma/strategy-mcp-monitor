import asyncio

import httpx
import pytest
from fastapi import APIRouter

from app.main import ShutdownSequence, request_exit, server_configs
from app.services import build_services
from app.settings.store import Settings
from app.web.app_factory import create_app


class _FakeServer:
    def __init__(self):
        self.should_exit = False
        self.force_exit = False


def test_first_signal_graceful_second_forces_exit():
    servers = [_FakeServer(), _FakeServer()]
    request_exit(servers)
    assert all(s.should_exit and not s.force_exit for s in servers)
    request_exit(servers)
    assert all(s.should_exit and s.force_exit for s in servers)


async def test_shutdown_runs_the_collectors_stop_while_the_servers_still_answer():
    """Task 15 carry: the agents' ``exit`` goes out over the Local channel, so the servers may only
    be asked to exit once the collectors (and with them the agent supervisor) have stopped."""
    servers = [_FakeServer(), _FakeServer()]
    release = asyncio.Event()
    seen = []

    async def stop_collectors():
        seen.append([s.should_exit for s in servers])
        await release.wait()

    shutdown = ShutdownSequence(servers, stop_collectors)
    shutdown.request()
    await asyncio.sleep(0)
    assert seen == [[False, False]]
    await asyncio.sleep(0.01)
    assert not any(s.should_exit for s in servers)  # still serving while the stop runs
    release.set()
    await shutdown.wait()
    assert all(s.should_exit and not s.force_exit for s in servers)


async def test_repeated_signals_during_the_collectors_stop_exit_then_force():
    servers = [_FakeServer()]
    release = asyncio.Event()
    calls = []

    async def stop_collectors():
        calls.append(1)
        await release.wait()

    shutdown = ShutdownSequence(servers, stop_collectors)
    shutdown.request()
    await asyncio.sleep(0)
    shutdown.request()  # impatient: stop serving now (graceful)
    assert servers[0].should_exit and not servers[0].force_exit
    release.set()
    await shutdown.wait()
    assert not servers[0].force_exit  # the stop finishing does not escalate to a force exit
    shutdown.request()
    assert servers[0].force_exit
    assert calls == [1]  # the collectors are stopped once


async def test_shutdown_asks_the_servers_to_exit_even_when_the_stop_fails():
    servers = [_FakeServer()]

    async def broken():
        raise RuntimeError("boom")

    shutdown = ShutdownSequence(servers, broken)
    shutdown.request()
    with pytest.raises(RuntimeError, match="boom"):
        await shutdown.wait()
    assert servers[0].should_exit


async def test_wait_without_a_request_returns_at_once():
    calls = []

    async def stop_collectors():
        calls.append(1)

    server = _FakeServer()
    await ShutdownSequence([server], stop_collectors).wait()
    assert calls == [] and not server.should_exit


def test_server_configs_ignore_proxy_headers_and_bound_shutdown(services):
    cfgs = server_configs(create_app("local", services), create_app("external", services))
    assert all(c.proxy_headers is False for c in cfgs)
    assert all(c.timeout_graceful_shutdown == 10 for c in cfgs)


async def test_framework_errors_use_error_code_bodies(local_client, external_client):
    r = await external_client.get("/api/bootstrap")
    assert r.status_code == 404 and r.json() == {"error": "not_found"}
    # Local: a wrong method is a plain 405. External: it must not reveal that the path exists
    # for another method (some paths are shared with local-only routes), so it is a 404.
    r = await local_client.post("/api/channel")
    assert r.status_code == 405 and r.json() == {"error": "method_not_allowed"} and "allow" in r.headers
    r = await external_client.post("/api/channel")
    assert r.status_code == 404 and r.json() == {"error": "not_found"} and "allow" not in r.headers


async def test_unhandled_exception_is_500_internal(services, capsys):
    app = create_app("local", services)
    router = APIRouter()

    @router.get("/t/boom")
    async def boom():
        raise RuntimeError("secret detail")

    @router.get("/t/num/{n}")
    async def num(n: int):
        return {"n": n}

    app.include_router(router)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8700") as c:
        r = await c.get("/t/boom")
        assert r.status_code == 500 and r.json() == {"error": "internal"}
        assert "secret detail" not in r.text
        r = await c.get("/t/num/abc")
        assert r.status_code == 422 and r.json() == {"error": "validation"}
    assert "secret detail" in capsys.readouterr().err


async def test_model_bug_in_route_is_500(services):
    app = create_app("local", services)
    router = APIRouter()

    @router.get("/t/model")
    async def model():
        Settings.model_validate({"ping_interval_sec": 0})

    app.include_router(router)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8700") as c:
        r = await c.get("/t/model")
    assert r.status_code == 500 and r.json() == {"error": "internal"}


def test_build_services_reuses_stored_otp_secret(tmp_path):
    first = build_services(tmp_path)
    secret1 = first.db.query("SELECT value FROM secrets WHERE name = 'otp_secret'")[0]["value"]
    first.db.close()
    second = build_services(tmp_path)
    rows = second.db.query("SELECT value FROM secrets WHERE name = 'otp_secret'")
    second.db.close()
    assert len(rows) == 1 and rows[0]["value"] == secret1
    assert len(bytes.fromhex(secret1)) == 32


# --- I1: both ports are ours before the collectors (and the agent launches) start ---------------

import socket  # noqa: E402

import app.main as main_mod  # noqa: E402
from app.collect.config import CollectorConfig  # noqa: E402
from app.main import bind_listener  # noqa: E402
from tests.live import free_port  # noqa: E402


class _CollectorsStarted(Exception):
    pass


def _connects(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


async def test_serve_binds_both_ports_before_the_collectors_start(tmp_path, monkeypatch):
    lp, ep = free_port(), free_port()
    seen = {}
    real_build = main_mod.build_services

    def build(root, **kw):
        services = real_build(root, **kw)

        async def start():
            seen["local"], seen["external"] = _connects(lp), _connects(ep)
            raise _CollectorsStarted

        services.collectors.start = start
        return services

    monkeypatch.setattr(main_mod, "build_services", build)
    with pytest.raises(_CollectorsStarted):
        await main_mod.serve(tmp_path, lp, ep, external_host="127.0.0.1",
                             collectors=CollectorConfig())
    assert seen == {"local": True, "external": True}
    assert not _connects(lp) and not _connects(ep)  # released again on the way out


async def test_serve_starts_nothing_when_the_local_port_is_taken(tmp_path, monkeypatch):
    holder = bind_listener("127.0.0.1", 0)
    lp = holder.getsockname()[1]
    started = []
    real_build = main_mod.build_services

    def build(root, **kw):
        services = real_build(root, **kw)

        async def start():
            started.append(True)

        services.collectors.start = start
        return services

    monkeypatch.setattr(main_mod, "build_services", build)
    try:
        with pytest.raises(OSError):
            await main_mod.serve(tmp_path, lp, free_port(), external_host="127.0.0.1",
                                 collectors=CollectorConfig())
    finally:
        holder.close()
    assert started == []


async def test_serve_starts_the_log_index_after_the_log_and_stops_it_before(tmp_path, monkeypatch):
    order = []
    real_build = main_mod.build_services

    def build(root, **kw):
        services = real_build(root, **kw)

        def record(name, fn):
            async def wrapped(*a, **k):
                order.append(name)
                return await fn(*a, **k)
            return wrapped

        services.log.start = record("log.start", services.log.start)
        services.log.stop = record("log.stop", services.log.stop)
        services.log_index.start = record("index.start", services.log_index.start)
        services.log_index.stop = record("index.stop", services.log_index.stop)

        async def start():
            order.append("collectors.start")
            raise _CollectorsStarted

        services.collectors.start = start
        return services

    monkeypatch.setattr(main_mod, "build_services", build)
    with pytest.raises(_CollectorsStarted):
        await main_mod.serve(tmp_path, free_port(), free_port(), external_host="127.0.0.1",
                             collectors=CollectorConfig())
    assert order == ["log.start", "index.start", "collectors.start", "index.stop", "log.stop"]
    assert (tmp_path / "data" / "index.db").is_file()


def test_bind_listener_is_exclusive():
    first = bind_listener("127.0.0.1", 0)
    try:
        with pytest.raises(OSError):
            bind_listener("127.0.0.1", first.getsockname()[1])
    finally:
        first.close()
