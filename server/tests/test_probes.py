import asyncio
import json
import os
import socket
import sys
import time

import httpx
import psutil
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route

from app.monitor import probes
from app.monitor.models import Issue
from app.monitor.probes import (
    McpPingClient,
    Prober,
    classify,
    is_local_host,
    local_addresses,
    parse_ping_output,
    probe_icmp,
    probe_tcp,
)
from tests.fakes import make_mcp
from tests.live import free_port, live_app


def fake_mcp(mode="json", delay=0.0, big=False, ping_error=False):
    seen = []; sessions = {"s1"}
    async def handler(request):
        body = await request.json(); seen.append((body["method"], request.headers.get("mcp-session-id")))
        await asyncio.sleep(delay)
        if body["method"] == "initialize":
            sessions.add("s1"); msg = {"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "f", "version": "1"}}}
            headers = {"Mcp-Session-Id": "s1"}
        elif "id" not in body:
            return Response(status_code=202)
        else:
            if request.headers.get("mcp-session-id") not in sessions: return Response(status_code=404)
            msg = {"jsonrpc": "2.0", "id": body["id"], **({"error": {"code": -1, "message": "x"}} if ping_error else {"result": {"pad": "x" * 100_000} if big else {}})}
            headers = {}
        if mode == "sse":
            async def gen(): yield f"event: message\ndata: {json.dumps(msg)}\n\n"
            return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)
        return JSONResponse(msg, headers=headers)
    app = Starlette(routes=[Route("/mcp", handler, methods=["POST"])])
    return app, seen, sessions

def odd_mcp(kind, log=None):
    """initialize/initialized behave; the ping reply is malformed in the way `kind` names."""
    served_pings = 0
    async def handler(request):
        nonlocal served_pings
        body = await request.json()
        if log is not None and "id" in body: log.append(body["method"])
        if body["method"] == "initialize":
            return JSONResponse({"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "2025-06-18"}}, headers={"Mcp-Session-Id": "s"})
        if "id" not in body:
            return Response(status_code=202)
        if kind == "ping404_after_first":
            served_pings += 1
            if served_pings > 1: return Response(status_code=404)
            return JSONResponse({"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if kind == "http500": return Response(status_code=500)
        if kind == "badjson": return PlainTextResponse("not json")
        if kind == "empty": return Response(status_code=202)
        if kind == "sse_other_id":
            async def gen(): yield f"data: {json.dumps({'jsonrpc': '2.0', 'id': 999, 'result': {}})}\n\n"
            return StreamingResponse(gen(), media_type="text/event-stream")
        if kind == "sse_open":  # replies at once, then keeps the stream open (CRLF line ends, split event)
            async def gen():
                msg = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {}})
                yield ": keepalive\r\n\r\n"; yield "data: " + msg[:5]; yield msg[5:] + "\r\n\r\n"; await asyncio.sleep(10)
            return StreamingResponse(gen(), media_type="text/event-stream")
        if kind == "sse_silent":  # never replies, never ends
            async def gen():
                while True: yield ": keepalive\n\n"; await asyncio.sleep(0.05)
            return StreamingResponse(gen(), media_type="text/event-stream")
        if kind == "sse_flood":
            async def gen():
                for _ in range(100): yield ": " + "x" * 1000 + "\n"
            return StreamingResponse(gen(), media_type="text/event-stream")
        raise AssertionError(kind)
    return Starlette(routes=[Route("/mcp", handler, methods=["POST"])])

@pytest.mark.parametrize("mode", ["json", "sse"])
async def test_mcp_ping_reuses_session(mode):
    app, seen, _ = fake_mcp(mode)
    async with live_app(app) as base, httpx.AsyncClient() as http:
        c = McpPingClient(http)
        r = await c.ping(base + "/mcp", 3.0)
        assert r.ok and r.latency_ms >= 0 and r.error is None
        assert seen == [("initialize", None), ("notifications/initialized", "s1"), ("ping", "s1")]
        assert (await c.ping(base + "/mcp", 3.0)).ok and seen[-1] == ("ping", "s1") and len(seen) == 4

async def test_session_expired_reinitializes():
    app, seen, sessions = fake_mcp()
    async with live_app(app) as base, httpx.AsyncClient() as http:
        c = McpPingClient(http); await c.ping(base + "/mcp", 3.0)
        sessions.clear()
        assert (await c.ping(base + "/mcp", 3.0)).ok
        assert [m for m, _ in seen].count("initialize") == 2

async def test_404_right_after_reinitialize_is_an_error_not_a_loop():
    pings = []
    async with live_app(odd_mcp("ping404_after_first", pings)) as base, httpx.AsyncClient() as http:
        c = McpPingClient(http)
        assert (await c.ping(base + "/mcp", 3.0)).ok
        pings.clear()
        r = await c.ping(base + "/mcp", 3.0)
    assert (r.ok, r.error) == (False, "http_404") and pings == ["ping", "initialize", "ping"]

async def test_forget_drops_the_cached_session():
    app, seen, _ = fake_mcp()
    async with live_app(app) as base, httpx.AsyncClient() as http:
        c = McpPingClient(http); await c.ping(base + "/mcp", 3.0); c.forget(base + "/mcp"); await c.ping(base + "/mcp", 3.0)
        assert [m for m, _ in seen].count("initialize") == 2

@pytest.mark.parametrize("kw,error", [({"ping_error": True}, "rpc_error"), ({"big": True}, "too_large")])
async def test_mcp_ping_bad_replies(kw, error):
    app, _, _ = fake_mcp(**kw)
    async with live_app(app) as base, httpx.AsyncClient() as http:
        r = await McpPingClient(http).ping(base + "/mcp", 3.0)
    assert (r.ok, r.error) == (False, error)

@pytest.mark.parametrize("kind,error", [
    ("http500", "http_500"), ("badjson", "bad_response"), ("empty", "no_reply"), ("sse_other_id", "no_reply"),
    ("sse_flood", "too_large"),
])
async def test_mcp_ping_odd_replies(kind, error):
    async with live_app(odd_mcp(kind)) as base, httpx.AsyncClient() as http:
        r = await McpPingClient(http).ping(base + "/mcp", 3.0)
    assert (r.ok, r.error) == (False, error)

async def test_sse_reply_returns_while_stream_stays_open():
    async with live_app(odd_mcp("sse_open")) as base, httpx.AsyncClient() as http:
        t = time.perf_counter(); r = await McpPingClient(http).ping(base + "/mcp", 3.0); took = time.perf_counter() - t
    assert r.ok and took < 2.0

async def test_endless_silent_sse_is_bounded_by_the_timeout():
    async with live_app(odd_mcp("sse_silent")) as base, httpx.AsyncClient() as http:
        t = time.perf_counter(); r = await McpPingClient(http).ping(base + "/mcp", 0.5); took = time.perf_counter() - t
    assert (r.ok, r.error) == (False, "timeout") and took < 1.5

async def test_mcp_ping_timeout():
    app, _, _ = fake_mcp(delay=2.0)
    async with live_app(app) as base, httpx.AsyncClient() as http:
        t = time.perf_counter(); r = await McpPingClient(http).ping(base + "/mcp", 0.5); took = time.perf_counter() - t
    assert (r.ok, r.error) == (False, "timeout") and took < 1.5

async def test_connect_refused_and_tcp():
    # Windows needs ~2 s to report a refused connection (SYN retransmits), so the timeout must exceed that.
    port = free_port()
    async with httpx.AsyncClient() as http:
        ping, tcp = await asyncio.gather(McpPingClient(http).ping(f"http://127.0.0.1:{port}/mcp", 3.0), probe_tcp("127.0.0.1", port, 3.0))
    assert ping.error == "connect" and (tcp.ok, tcp.error) == (False, "connect")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); s.listen()
        assert (await probe_tcp("127.0.0.1", s.getsockname()[1], 1.0)).ok is True

@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
async def test_icmp_localhost():
    assert (await probe_icmp("127.0.0.1", 1.0)).ok is True

def test_parse_ping_output():
    assert parse_ping_output("Reply from 1.1.1.1: bytes=32 time=12ms TTL=57") == 12.0
    assert parse_ping_output("127.0.0.1의 응답: 바이트=32 시간<1ms TTL=128") == 1.0
    assert parse_ping_output("Destination host unreachable.") is None
    assert parse_ping_output("요청 시간이 만료되었습니다.") is None

D = dict(local=True, port_known=True, listening_pid=10, process_name=None, expected_process_name=None, probe_ok=True, icmp_ok=None)
@pytest.mark.parametrize("kw,expected", [
    ({"listening_pid": None, "probe_ok": False}, Issue.PROCESS_DOWN),
    ({"listening_pid": None, "probe_ok": True}, None),  # port snapshot lag right after a start: healthy this round
    ({"process_name": "node.exe", "expected_process_name": "python.exe"}, Issue.WRONG_PROCESS),
    ({"process_name": "Python.EXE", "expected_process_name": "python.exe"}, None),
    ({"process_name": None, "expected_process_name": "python.exe"}, None),
    ({"probe_ok": False}, Issue.UNRESPONSIVE),
    ({"local": False, "listening_pid": None}, None),
    ({"local": False, "listening_pid": None, "probe_ok": False, "icmp_ok": False}, Issue.NETWORK_DOWN),
    ({"local": False, "listening_pid": None, "probe_ok": False, "icmp_ok": True}, Issue.UNRESPONSIVE),
    ({"local": False, "listening_pid": None, "probe_ok": False, "icmp_ok": None}, Issue.UNRESPONSIVE),
])
def test_classify(kw, expected):
    assert classify(**{**D, **kw}) is expected

def test_classify_port_unknown():
    assert classify(**{**D, "port_known": False, "listening_pid": None, "probe_ok": False}) is Issue.UNRESPONSIVE
    assert classify(**{**D, "port_known": False, "listening_pid": None}) is None

def test_listening_ports_and_local():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); s.listen()
        assert probes.listening_ports()[s.getsockname()[1]] == os.getpid()
    local = local_addresses()
    assert all(is_local_host(h, local) for h in ("127.0.0.1", "localhost", "::1", socket.gethostname().lower()))
    assert is_local_host("203.0.113.5", local) is False

async def test_check_process_down(clock):
    p = Prober(clock)
    try:
        r = await p.check(make_mcp(port=free_port()))
        assert r.issue is Issue.PROCESS_DOWN and r.at == clock.now() and r.pid is None
    finally:
        await p.aclose()

async def test_check_survives_port_lookup_failure(clock, monkeypatch):
    def denied(): raise psutil.AccessDenied()
    monkeypatch.setattr(probes, "listening_ports", denied)
    p = Prober(clock)
    try:
        r = await p.check(make_mcp(port=free_port()))
        assert r.issue is Issue.UNRESPONSIVE
        assert r.error is not None and "port_lookup:AccessDenied" in r.error  # F13: surfaced, not swallowed
    finally:
        await p.aclose()

async def test_check_healthy_listener_with_mcp_ping(clock):
    app, _, _ = fake_mcp()
    async with live_app(app) as base:
        port = int(base.rsplit(":", 1)[1])
        p = Prober(clock)
        try:
            r = await p.check(make_mcp(port=port, expected_process_name=psutil.Process().name()))
            assert (r.issue, r.pid, r.error) == (None, os.getpid(), None) and r.latency_ms >= 0 and r.process_name
            wrong = await p.check(make_mcp(port=port, expected_process_name="definitely-not-this.exe"))
            assert wrong.issue is Issue.WRONG_PROCESS
        finally:
            await p.aclose()

async def test_check_tcp_probe_reports_listener_pid(clock):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); s.listen()
        p = Prober(clock)
        try:
            r = await p.check(make_mcp(port=s.getsockname()[1], probe="tcp"))
            assert (r.issue, r.pid, r.error) == (None, os.getpid(), None)
        finally:
            await p.aclose()

async def test_port_snapshot_shared_within_ttl(clock, monkeypatch):
    calls = []
    real = probes.listening_ports
    def counting(): calls.append(1); return real()
    monkeypatch.setattr(probes, "listening_ports", counting)
    p = Prober(clock)
    try:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); s.listen()
            await asyncio.gather(*(p.check(make_mcp(i, port=s.getsockname()[1], probe="tcp")) for i in range(1, 6)))
        assert len(calls) == 1
    finally:
        await p.aclose()

async def test_remote_probe_failure_uses_icmp_result(clock, monkeypatch):
    async def icmp(host, timeout): return probes.ProbeResult(False, None, "no_reply")
    monkeypatch.setattr(probes, "probe_icmp", icmp)
    monkeypatch.setattr(probes, "is_local_host", lambda host, local: False)
    p = Prober(clock, timeout=0.5)
    try:
        r = await p.check(make_mcp(port=free_port()))
        assert r.issue is Issue.NETWORK_DOWN and r.pid is None and r.error in ("connect", "timeout")
    finally:
        await p.aclose()

async def test_prober_forget_and_injected_client_stays_open(clock):
    app, seen, _ = fake_mcp()
    async with live_app(app) as base, httpx.AsyncClient() as http:
        p = Prober(clock, http=http); m = make_mcp(port=int(base.rsplit(":", 1)[1]))
        await p.probe(m); p.forget(m.id); await p.probe(m)
        assert [x for x, _ in seen].count("initialize") == 2
        await p.aclose()
        assert not http.is_closed
