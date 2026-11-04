"""Probes against a real dummy MCP (dummy-mcps/, started as a subprocess with --chaos)."""
import json
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import psutil
import pytest

from app.monitor.models import Issue
from app.monitor.probes import McpPingClient, Prober, listening_ports
from tests.fakes import make_mcp
from tests.live import free_port

DUMMY_DIR = Path(__file__).resolve().parents[2] / "dummy-mcps"
DUMMY_PYTHON = DUMMY_DIR / ".venv" / "Scripts" / "python.exe"

pytestmark = pytest.mark.skipif(not DUMMY_PYTHON.exists(), reason="dummy-mcps venv not installed")


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        parent = psutil.Process(proc.pid)
        victims = parent.children(recursive=True) + [parent]
    except psutil.NoSuchProcess:
        victims = []
    for v in victims:
        try:
            v.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(victims, timeout=10)
    proc.wait(10)


@contextmanager
def dummy_mcp(tmp_path):
    """Run `python -m calculator --port <free> --chaos`; yields the port; kills the whole process tree after."""
    port = free_port()
    with (tmp_path / f"dummy-{port}.log").open("wb") as log:
        proc = subprocess.Popen(
            [str(DUMMY_PYTHON), "-m", "calculator", "--port", str(port), "--chaos"],
            cwd=DUMMY_DIR, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 20
            while True:
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                    break
                except OSError:
                    assert proc.poll() is None and time.monotonic() < deadline, "dummy MCP did not start"
                    time.sleep(0.1)
            yield port
        finally:
            _kill_tree(proc)


@pytest.fixture(scope="module")
def shared_dummy(tmp_path_factory):
    with dummy_mcp(tmp_path_factory.mktemp("dummy")) as port:
        yield port


class Wire:
    """httpx event hooks that record every request's JSON-RPC method and the reply's content type."""

    def __init__(self) -> None:
        self.methods: list[str] = []
        self.content_types: list[str] = []
        self.corrupt_session_for: str | None = None

    async def on_request(self, request: httpx.Request) -> None:
        method = json.loads(request.content)["method"]
        self.methods.append(method)
        if method == self.corrupt_session_for:
            request.headers["mcp-session-id"] = "no-such-session"

    async def on_response(self, response: httpx.Response) -> None:
        self.content_types.append(response.headers.get("content-type", ""))

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(event_hooks={"request": [self.on_request], "response": [self.on_response]})


async def test_ping_reports_latency_and_reuses_the_session(shared_dummy):
    wire = Wire()
    async with wire.client() as http:
        client = McpPingClient(http)
        first = await client.ping(f"http://127.0.0.1:{shared_dummy}/mcp", 3.0)
        second = await client.ping(f"http://127.0.0.1:{shared_dummy}/mcp", 3.0)
    assert first.ok and first.error is None and 0 <= first.latency_ms < 3000
    assert second.ok
    assert wire.methods == ["initialize", "notifications/initialized", "ping", "ping"]  # one handshake only
    assert wire.content_types[0].startswith(("application/json", "text/event-stream"))


async def test_expired_session_is_reinitialized_once(shared_dummy):
    wire = Wire()
    url = f"http://127.0.0.1:{shared_dummy}/mcp"
    async with wire.client() as http:
        client = McpPingClient(http)
        assert (await client.ping(url, 3.0)).ok
        wire.corrupt_session_for = "ping"  # the server now sees an unknown session id on every ping
        r = await client.ping(url, 3.0)
    assert (r.ok, r.error) == (False, "http_404")  # re-initialized once, the retry carries the bad id again
    assert wire.methods == ["initialize", "notifications/initialized", "ping",
                            "ping", "initialize", "notifications/initialized", "ping"]


async def test_prober_check_healthy_dummy(shared_dummy, clock):
    prober = Prober(clock)
    try:
        r = await prober.check(make_mcp(port=shared_dummy, expected_process_name=psutil.Process().name()))
        assert r.error is None and r.latency_ms is not None
        assert r.pid == listening_ports()[shared_dummy] and r.pid is not None
        assert r.process_name and r.issue is None
    finally:
        await prober.aclose()


async def test_hang_times_out_within_the_probe_timeout(tmp_path, clock):
    with dummy_mcp(tmp_path) as port:
        async with httpx.AsyncClient() as http:
            assert (await McpPingClient(http).ping(f"http://127.0.0.1:{port}/mcp", 3.0)).ok
            r = await http.post(f"http://127.0.0.1:{port}/chaos/hang", params={"sec": 6})
            assert r.status_code == 202
            time.sleep(0.3)  # the loop is blocked from here on
        prober = Prober(clock, timeout=1.0)
        try:
            t = time.perf_counter()
            probe = await prober.probe(make_mcp(port=port))
            took = time.perf_counter() - t
            assert (probe.ok, probe.error) == (False, "timeout") and took < 2.0
            check = await prober.check(make_mcp(port=port))
            assert check.issue is Issue.UNRESPONSIVE and check.pid is not None  # alive, listening, not answering
        finally:
            await prober.aclose()


async def test_crash_is_connection_refused_then_process_down(tmp_path, clock):
    with dummy_mcp(tmp_path) as port:
        async with httpx.AsyncClient() as http:
            assert (await http.post(f"http://127.0.0.1:{port}/chaos/crash")).status_code == 202
        deadline = time.monotonic() + 10
        while listening_ports().get(port) is not None:
            assert time.monotonic() < deadline, "dummy did not exit"
            time.sleep(0.1)
        prober = Prober(clock)  # default 3 s: Windows needs ~2 s to report a refused connection
        try:
            check = await prober.check(make_mcp(port=port))
            assert (check.issue, check.pid, check.error) == (Issue.PROCESS_DOWN, None, "connect")
        finally:
            await prober.aclose()
