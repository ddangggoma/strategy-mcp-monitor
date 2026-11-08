"""Real-agent scenarios: the Local app on a loopback port in this process, the real peer resolver,
the real local launcher and a real agent with ``--dialog print`` (the agent runs in this Windows
session, so the TCP-peer → session check really runs), sessions from a JSON file. Every scenario
runs with both agents: ``[python]`` = ``python -m mcp_agent``, ``[desktop]`` = the Rust
``mcp-monitor.exe agent`` (Plan 6 Task 11; skipped unless ``MCPMON_DESKTOP_EXE`` names the built exe).

Run explicitly (excluded from the default run):
    uv run python -m pytest -m integration tests/test_integration_agent.py -v
and with MCPMON_DESKTOP_EXE = <repo>/desktop/target/debug/mcp-monitor.exe (after ``cargo build``)
the ``[desktop]`` half runs too.
"""
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import psutil
import pytest
import win32api
import win32con
import win32event
import win32process

from app.activity.agent_supervisor import AgentOptions
from app.clock import SystemClock
from app.collect.config import CollectorConfig
from app.services import build_services
from app.sessions.jsonsource import JsonFileWtsSource
from app.web.app_factory import create_app
from app.win.ffi import current_session_id
from app.win.launch import LocalLauncher
from app.win.peer import PsutilPeerResolver
from tests.live import free_port, live_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows only"),
]
REPO = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO / "server"
DESKTOP_EXE = os.environ.get("MCPMON_DESKTOP_EXE")
AGENTS = ["python", "desktop"]


def desktop_exe() -> str:
    if not DESKTOP_EXE:
        pytest.skip("set MCPMON_DESKTOP_EXE to the built mcp-monitor.exe")
    if not Path(DESKTOP_EXE).is_file():
        pytest.fail(f"MCPMON_DESKTOP_EXE={DESKTOP_EXE} is not a file")
    return DESKTOP_EXE


def agent_options(kind: str, run: Path) -> AgentOptions:
    common = dict(dialog="print", url_dir=run, backoff=(0.5, 1, 2), exit_grace_sec=1.0, tick_sec=0.2)
    if kind == "desktop":
        exe = desktop_exe()
        return AgentOptions(command=(exe, "agent"), agent_dir=Path(exe).parent, **common)
    return AgentOptions(agent_dir=REPO / "agent", **common)


def write_sessions(path, *sessions):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"sessions": list(sessions)}), "utf-8")
    os.replace(tmp, path)


def rdp(**kw):
    base = {"session_id": "self", "user": "hong", "domain": "CORP", "client_ip": "10.0.3.21", "client_name": "HONG-LAPTOP",
            "logon_at": "2026-11-04T13:00:00+09:00", "connected_at": "2026-11-04T13:00:00+09:00", "state": "active"}
    base.update(kw)
    return base


def opens(url_file):
    return [line for line in (url_file.read_text("utf-8").splitlines() if url_file.exists() else []) if line.startswith("OPEN ")]


async def wait(pred, timeout=20.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not pred():
        assert loop.time() < end, "timed out"
        await asyncio.sleep(0.1)


async def events(svc, cat):
    await svc.log.flush()
    out = []
    for f in sorted(svc.paths.logs_dir.glob("*.jsonl")):
        out += [e for e in map(json.loads, f.read_text("utf-8").splitlines()) if e["cat"] == cat]
    return out


def is_agent(cmdline: list[str]) -> bool:
    """An agent's own command line: ``<python> -m mcp_agent …`` or ``…/mcp-monitor.exe agent …``
    (F02: never a substring — the repo folder ``strategy-mcp-monitor`` is in the server's paths)."""
    if cmdline[1:3] == ["-m", "mcp_agent"]:
        return True
    return len(cmdline) > 1 and Path(cmdline[0]).name.lower() == "mcp-monitor.exe" and cmdline[1] == "agent"


def agents_of(root: Path) -> list[psutil.Process]:
    """Live agent processes started for this data root (their ``--url-file`` is under it)."""
    found = []
    for p in psutil.process_iter(["cmdline"]):
        cmdline = p.info["cmdline"] or []
        if is_agent(cmdline) and any(str(root) in arg for arg in cmdline):
            found.append(p)
    return found


def test_agents_are_told_apart_by_their_own_command_line():
    base = r"C:\work\strategy-mcp-monitor"
    assert is_agent([r"C:\py\python.exe", "-m", "mcp_agent", "--server", "http://127.0.0.1:1"])
    assert is_agent([rf"{base}\desktop\target\debug\MCP-Monitor.exe", "agent", "--dialog", "print"])
    for other in (
        [rf"{base}\server\.venv\Scripts\python.exe", "-m", "app", "--root", rf"{base}\tmp"],
        [r"C:\py\python.exe", "-m", "tests.desktop_bundle_main", rf"{base}\mcp-monitor.exe", "--root", "x"],
        [rf"{base}\mcp-monitor.exe", "app"],
        [rf"{base}\mcp-monitor-server.exe", "agent"],
        [r"C:\py\python.exe", "-c", "import mcp_agent"],
        [rf"{base}\mcp-monitor.exe"],
        [],
    ):
        assert not is_agent(other), other


@pytest.fixture(params=AGENTS)
async def stack(request, tmp_path):
    sessions = tmp_path / "sessions.json"
    write_sessions(sessions)
    run = tmp_path / "run"
    run.mkdir()
    cfg = CollectorConfig(wts=JsonFileWtsSource(sessions, SystemClock()), poll_interval_sec=0.2, launcher=LocalLauncher(),
                          agent=agent_options(request.param, run))
    svc = build_services(tmp_path, collectors=cfg, peer_resolver=PsutilPeerResolver())
    await svc.log.start()
    await svc.monitor.start(run_loops=False)
    try:
        async with live_app(create_app("local", svc)) as base:
            svc.agents.configure(base)
            svc.agent_supervisor.configure(base)
            await svc.collectors.start()
            try:
                await wait(lambda: svc.rdp.ready)
                yield svc, base, sessions, run / f"agent-{current_session_id()}.url"
            finally:
                await svc.collectors.stop()
    finally:
        await svc.monitor.stop()
        await svc.log.stop()
        svc.db.close()
    # F07: the supervisor's stop asked the agents to exit (or killed them); none outlives the stack
    deadline = time.monotonic() + 10
    while agents_of(tmp_path) and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    assert agents_of(tmp_path) == []


async def test_real_agent_shows_and_acknowledges_notice(stack):
    svc, base, sessions, url_file = stack
    write_sessions(sessions, rdp())
    await wait(lambda: len(opens(url_file)) == 1)
    token = parse_qs(urlsplit(opens(url_file)[0].split(" ", 2)[2]).fragment)["t"][0]
    async with httpx.AsyncClient(base_url=base) as c:
        assert (await c.post("/api/notice/display/open", headers={"X-Notice-Token": token})).status_code == 200
        assert (await c.post("/api/notice/display/ack", headers={"X-Notice-Token": token})).status_code == 204
    await wait(lambda: "CLOSE" in url_file.read_text("utf-8"))
    assert [e["event"] for e in await events(svc, "notice")] == ["notice_shown", "notice_acknowledged"]
    assert svc.rdp.board_sessions()[0]["notice_acknowledged"] is True


async def test_killing_the_agent_relaunches_it_and_reshows_pending_notice(stack):
    svc, base, sessions, url_file = stack
    write_sessions(sessions, rdp())
    await wait(lambda: len(opens(url_file)) == 1)
    sid = current_session_id()
    first_pid = svc.agents.slot(sid).pid
    subprocess.run(["taskkill", "/PID", str(first_pid), "/T", "/F"], capture_output=True, check=True)
    await wait(lambda: any(r["event"] == "agent_exited" for r in svc.tamper.recent()))
    await wait(lambda: len(opens(url_file)) == 2)
    assert svc.agents.slot(sid).pid not in (None, first_pid)
    assert "agent_exited" in [e["reason"] for e in await events(svc, "notice") if e["event"] == "notice_unacknowledged"]


async def test_reconnect_reshows_notice(stack):
    svc, base, sessions, url_file = stack
    write_sessions(sessions, rdp())
    await wait(lambda: len(opens(url_file)) == 1)
    write_sessions(sessions, rdp(state="disconnected"))
    await wait(lambda: svc.rdp.board_sessions() == [])
    write_sessions(sessions, rdp(connected_at="2026-11-04T13:30:00+09:00"))
    await wait(lambda: len(opens(url_file)) == 2)
    d1, d2 = (int(line.split()[1]) for line in opens(url_file))
    assert d1 != d2 and svc.displays.get(d1).closed_reason == "superseded" and svc.displays.get(d2).kind == "reconnect"
    assert [e["kind"] for e in await events(svc, "session") if e["event"] == "connect"] == ["logon", "reconnect"]


def _answers(port: int) -> bool:
    try:
        httpx.get(f"http://127.0.0.1:{port}/api/channel", timeout=0.2)
        return True
    except httpx.HTTPError:
        return False


@pytest.mark.parametrize("kind", AGENTS)
def test_service_stop_tells_the_agent_to_exit_and_closes_its_notice(tmp_path, kind):
    """Task 15 carry: ``serve()`` keeps the Local server answering while the collectors stop, so the
    supervisor's ``exit`` reaches the agent, which closes its notice window and exits by itself
    (before the fix the servers were gone first: no CLOSE line, the agent was killed after 2 s).
    ``[desktop]``: the server runs as from a desktop bundle, so its agent is ``mcp-monitor.exe agent``
    (F02/F09: the Rust agent's exit, final event flush included, fits the 2 s grace)."""
    server = [sys.executable, "-m", "app"]
    if kind == "desktop":
        server = [sys.executable, "-m", "tests.desktop_bundle_main", desktop_exe()]
    sessions = tmp_path / "sessions.json"
    write_sessions(sessions, rdp())
    url_file = tmp_path / "run" / f"agent-{current_session_id()}.url"
    lp, ep = free_port(), free_port()
    out_path = tmp_path / "server-output.txt"
    with out_path.open("wb") as out:
        p = subprocess.Popen(
            [*server, "--root", str(tmp_path), "--local-port", str(lp), "--external-port", str(ep),
             "--session-source", f"json:{sessions}", "--agent-launcher", "local", "--agent-dialog", "print",
             "--activity", "off"],
            cwd=SERVER_DIR, stdout=out, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            deadline = time.monotonic() + 20
            while not (_answers(lp) and len(opens(url_file)) == 1):
                assert p.poll() is None and time.monotonic() < deadline, "server or agent did not start"
                time.sleep(0.1)
            [agent] = agents_of(tmp_path)
            # a handle held across the exit keeps the agent's exit code readable
            handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.SYNCHRONIZE,
                                          False, agent.pid)
            p.send_signal(signal.CTRL_BREAK_EVENT)
            code = p.wait(30)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait(10)
            for leftover in agents_of(tmp_path):
                leftover.kill()
    output = out_path.read_text("utf-8", errors="replace")
    assert code == 0 and "Traceback" not in output, output
    [display_id] = [line.split()[1] for line in opens(url_file)]
    assert url_file.read_text("utf-8").splitlines()[-1] == f"CLOSE {display_id}"
    try:
        assert win32event.WaitForSingleObject(handle, 5000) == win32event.WAIT_OBJECT_0
        # 0 = the agent was told to exit; a kill by the supervisor (taskkill /F) gives 1
        assert win32process.GetExitCodeProcess(handle) == 0
    finally:
        handle.Close()
