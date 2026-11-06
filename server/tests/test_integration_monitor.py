"""End-to-end monitor scenario: real dummy MCPs, the example scripts, the real runner and prober.

Run explicitly (excluded from the default run):
    uv run python -m pytest -m integration -q -W error

Time budget: a refused loopback connect takes ~2.05 s on Windows, so every dead-MCP check round
costs ~2 s on top of the 5 s issue-check interval; the waits below allow for that. The whole
scenario typically needs 50-70 s.
"""
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import psutil
import pytest
import pytest_asyncio

from app.monitor.probes import listening_ports
from app.monitor.scripts import ScriptUpload
from app.services import build_services
from app.web.app_factory import create_app
from tests.fakes import CapturingOtpProvider, FakeProber
from tests.live import free_port
from tests.mcp_helpers import make_user, seed_mcp
from tests.test_auth_api import bootstrap, login

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows only"),
    pytest.mark.timeout(240),  # the scenario needs 50-70 s; above the default 120 s per-test cap
]
DUMMY = Path(__file__).resolve().parents[2] / "dummy-mcps"
SCRIPTS = {
    k: {"ext": ".ps1", "content": (DUMMY / "examples" / f"{k}.ps1").read_text("utf-8-sig")}
    for k in ("start", "stop", "restart")
}
TIMING = {
    "expected_process_name": "python.exe",
    "action_delay_sec": 1,
    "startup_grace_sec": 1,
    "max_auto_actions": 2,
    "window_sec": 600,
    "script_timeout_sec": 30,
}


def _kill_with_launcher(pid: int) -> None:
    """Kill a dummy MCP and the venv launcher python.exe that spawned it."""
    try:
        proc = psutil.Process(pid)
        victims = [proc]
        parent = proc.parent()
        if parent is not None and parent.name().lower() == "python.exe":
            victims.append(parent)
    except psutil.Error:
        return
    for victim in victims:
        try:
            victim.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(victims, timeout=10)


@pytest_asyncio.fixture
async def live(tmp_path, monkeypatch):
    assert (DUMMY / ".venv" / "Scripts" / "python.exe").exists(), "run `uv sync` in dummy-mcps first"
    run_dir = tmp_path / "run"
    monkeypatch.setenv("DUMMY_MCPS_DIR", str(DUMMY))
    monkeypatch.setenv("DUMMY_MCP_RUN_DIR", str(run_dir))
    monkeypatch.setenv("DUMMY_MCP_CHAOS", "1")
    svc = build_services(tmp_path / "root", otp_provider=CapturingOtpProvider())  # real runner + prober
    svc.settings.update({"ping_interval_sec": 1, "issue_check_interval_sec": 5, "confirm_interval_sec": 1})
    ports: list[int] = []
    await svc.log.start()
    await svc.monitor.start()
    transport = httpx.ASGITransport(app=create_app("local", svc))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8700") as c:
            yield svc, c, ports
    finally:
        await svc.monitor.stop()
        await svc.log.stop()
        svc.db.close()
        for pid_file in run_dir.glob("*.pid"):  # leftovers from a failed run
            try:
                _kill_with_launcher(int(pid_file.read_text()))
            except ValueError:
                pass
        for port in ports:
            pid = listening_ports().get(port)
            if pid:
                _kill_with_launcher(pid)


async def board_item(c, mcp_id):
    return next(i for i in (await c.get("/api/board")).json()["mcps"] if i["id"] == mcp_id)


async def wait_state(c, mcp_id, states, timeout):
    deadline = time.monotonic() + timeout
    item = None
    while time.monotonic() < deadline:
        item = await board_item(c, mcp_id)
        if item["state"] in states:
            return item
        await asyncio.sleep(0.2)
    pytest.fail(f"mcp {mcp_id} not in {states} after {timeout}s: {item}")


async def chaos(port, path):
    async with httpx.AsyncClient(trust_env=False) as h:
        try:
            await h.post(f"http://127.0.0.1:{port}{path}", timeout=2)
        except httpx.HTTPError:
            pass  # crash closes the connection, hang never answers


def last_action(svc, mcp_id):
    a = svc.history.actions(mcp_id)[0]
    return a, f"{a.result.status}: {a.result.stdout}{a.result.stderr}"


async def test_crash_hang_and_failed(live):
    svc, c, port_list = live
    await bootstrap(c)
    await login(c, svc)
    h = {"X-CSRF-Token": c.csrf}
    ports, ids = {"calculator": free_port(), "seoul-clock": free_port()}, {}
    port_list.extend(ports.values())
    for name, port in ports.items():
        r = await c.post(
            "/api/mcps",
            json={"name": name, "host": "127.0.0.1", "port": port, **TIMING, "scripts": SCRIPTS},
            headers=h,
        )
        assert r.status_code == 201, r.text
        ids[name] = r.json()["id"]
        assert (await c.post(f"/api/mcps/{ids[name]}/actions/start", headers=h)).status_code == 202
    for i in ids.values():
        await wait_state(c, i, {"HEALTHY"}, 30)
    calc, other = ids["calculator"], ids["seoul-clock"]

    samples = []

    async def sample():
        while True:
            t = time.perf_counter()
            item = await board_item(c, other)
            dt = time.perf_counter() - t
            age = time.time() - datetime.fromisoformat(item["last_check_at"]).timestamp()
            samples.append((dt, age, item["state"]))
            await asyncio.sleep(0.2)

    sampler = asyncio.create_task(sample())
    try:
        await chaos(ports["calculator"], "/chaos/crash")  # 1) crash -> automatic start
        await wait_state(c, calc, {"SUSPECT", "ACTION"}, 15)
        await wait_state(c, calc, {"HEALTHY"}, 30)
        a, out = last_action(svc, calc)
        assert (a.kind, a.trigger, a.reason, a.result.status) == ("start", "auto", "PROCESS_DOWN", "ok"), out

        await chaos(ports["calculator"], "/chaos/hang?sec=120")  # 2) hang -> automatic restart
        await wait_state(c, calc, {"SUSPECT", "ACTION"}, 20)
        await wait_state(c, calc, {"HEALTHY"}, 40)
        a, out = last_action(svc, calc)
        assert (a.kind, a.trigger, a.reason, a.result.status) == ("restart", "auto", "UNRESPONSIVE", "ok"), out

        await chaos(ports["calculator"], "/chaos/crash")  # 3) limit exhausted -> stop + FAILED
        await wait_state(c, calc, {"FAILED"}, 40)
        await svc.monitor.wait_idle()
        a, out = last_action(svc, calc)
        assert (a.kind, a.trigger, a.result.status) == ("stop", "auto", "ok"), out
        assert listening_ports().get(ports["calculator"]) is None
    finally:
        sampler.cancel()
        await asyncio.gather(sampler, return_exceptions=True)
    assert samples and max(s[0] for s in samples) < 0.5  # the API kept answering
    assert max(s[1] for s in samples) < 3.5  # the other MCP's pings kept flowing
    assert {s[2] for s in samples} == {"HEALTHY"}


# ---- Plan 5 Task 7 (W21): a service stop kills the tree of a script still running after the grace ----

async def test_service_stop_kills_abandoned_script_tree(tmp_path):
    from app.clock import SystemClock
    clock = SystemClock()
    svc = build_services(tmp_path, clock=clock, otp_provider=CapturingOtpProvider(), prober=FakeProber(clock))
    await svc.log.start()
    pidfile = tmp_path / "child.pid"
    hang = (f"$c = Start-Process ping -ArgumentList '-n','60','127.0.0.1' -PassThru -WindowStyle Hidden\n"
            f"Set-Content -Path '{pidfile}' -Value $c.Id\nStart-Sleep 60\n")
    owner = make_user(svc, "o@x.com")
    m = seed_mcp(svc, owner, scripts={"start": ScriptUpload(".ps1", hang), "stop": ScriptUpload(".ps1", "exit 0\n")})
    svc.monitor.manual_action(m.id, "start", owner)
    for _ in range(150):
        if pidfile.exists() and pidfile.read_text("utf-8-sig").strip(): break
        await asyncio.sleep(0.1)
    child = int(pidfile.read_text("utf-8-sig").strip())
    await svc.monitor.stop(grace_sec=0.5, kill_abandoned=True)
    await svc.log.stop(); svc.db.close()
    stop = [json.loads(x) for x in next((tmp_path / "logs").glob("*.jsonl")).read_text("utf-8").split("\n")
            if x and '"monitor.stop"' in x][-1]
    assert not psutil.pid_exists(child) and stop["killed"] >= 2 and stop["abandoned"] == 1
