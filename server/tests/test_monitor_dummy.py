"""Monitor end to end with the real ScriptRunner, the real Prober, a real dummy MCP and its example scripts."""
import asyncio
import sys
import time
from pathlib import Path

import httpx
import psutil
import pytest

from app.monitor.models import McpState as S
from app.monitor.probes import listening_ports
from app.monitor.scripts import ScriptUpload
from app.services import build_services
from tests.fakes import CapturingOtpProvider
from tests.live import free_port
from tests.mcp_helpers import make_user, seed_mcp

DUMMY_DIR = Path(__file__).resolve().parents[2] / "dummy-mcps"
DUMMY_PYTHON = DUMMY_DIR / ".venv" / "Scripts" / "python.exe"

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not DUMMY_PYTHON.exists(), reason="Windows + dummy-mcps venv only"
)


async def _wait_port_free(port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while (await asyncio.to_thread(listening_ports)).get(port) is not None:
        assert time.monotonic() < deadline, f"port {port} still listening"
        await asyncio.sleep(0.1)


def _kill_listener(port: int) -> None:
    """Last-resort cleanup: kill the dummy listening on `port` (and its venv launcher parent)."""
    pid = listening_ports().get(port)
    if not pid:
        return
    try:
        proc = psutil.Process(pid)
        victims = [proc] + [p for p in [proc.parent()] if p and p.name().lower() == "python.exe"]
    except psutil.Error:
        return
    for v in victims:
        try:
            v.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(victims, timeout=10)


class Ticker:
    """Measures the longest gap between 20 ms sleeps: how long the event loop was blocked."""

    def __init__(self) -> None:
        self.max_gap = 0.0
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        last = loop.time()
        while True:
            await asyncio.sleep(0.02)
            now = loop.time()
            self.max_gap = max(self.max_gap, now - last)
            last = now

    def __enter__(self):
        self._task = asyncio.get_running_loop().create_task(self._run())
        return self

    def __exit__(self, *exc):
        self._task.cancel()


async def test_crash_is_restarted_by_start_script(tmp_path, monkeypatch):
    monkeypatch.setenv("DUMMY_MCPS_DIR", str(DUMMY_DIR))
    monkeypatch.setenv("DUMMY_MCP_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("DUMMY_MCP_CHAOS", "1")
    svc = build_services(tmp_path / "root", otp_provider=CapturingOtpProvider())  # real runner + prober
    await svc.log.start()
    mon = svc.monitor
    port = free_port()
    try:
        owner = make_user(svc, "o@x.com")
        scripts = {k: ScriptUpload(".ps1", (DUMMY_DIR / "examples" / f"{k}.ps1").read_text("utf-8-sig"))
                   for k in ("start", "stop")}  # no restart script: not needed for a crash
        m = seed_mcp(svc, owner, scripts=scripts, name="calculator", port=port,
                     action_delay_sec=1, startup_grace_sec=0)
        await mon.start(run_loops=False)

        mon.manual_action(m.id, "start", owner)
        with Ticker() as ticker:
            await mon.wait_idle()
        first = svc.history.actions(m.id)[0]
        assert first.result.status == "ok", first.result.stdout + first.result.stderr
        assert ticker.max_gap < 0.3  # the loop kept running while start.ps1 ran
        assert mon.engine(m.id).state == S.RECOVERING
        await mon.confirm_round(); await mon.wait_idle()
        assert mon.engine(m.id).state == S.HEALTHY

        async with httpx.AsyncClient(trust_env=False) as http:
            assert (await http.post(f"http://127.0.0.1:{port}/chaos/crash")).status_code == 202
        await _wait_port_free(port)
        await mon.issue_round(); await mon.wait_idle()  # refused connect: ~2 s on Windows
        assert mon.board_item(m.id)["issue"] == "PROCESS_DOWN"
        await asyncio.sleep(1.1)  # action_delay_sec
        await mon.confirm_round()
        with Ticker() as ticker:
            await mon.wait_idle()
        auto = svc.history.actions(m.id)[0]
        assert (auto.kind, auto.trigger, auto.reason, auto.result.status) == ("start", "auto", "PROCESS_DOWN", "ok"), \
            auto.result.stdout + auto.result.stderr
        assert ticker.max_gap < 0.3
        assert listening_ports().get(port) is not None
        await mon.confirm_round(); await mon.wait_idle()
        assert mon.engine(m.id).state == S.HEALTHY

        mon.manual_action(m.id, "stop", owner); await mon.wait_idle()
        assert svc.history.actions(m.id)[0].result.status == "ok"
        await _wait_port_free(port)
        assert mon.engine(m.id).state == S.MAINTENANCE
    finally:
        await mon.stop()
        await asyncio.to_thread(_kill_listener, port)
        await svc.log.stop()
        svc.db.close()
