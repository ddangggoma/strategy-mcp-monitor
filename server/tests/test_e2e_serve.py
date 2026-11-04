import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from tests.live import free_port

SERVER_DIR = Path(__file__).resolve().parents[1]


def _answers(port: int) -> bool:
    try:
        httpx.get(f"http://127.0.0.1:{port}/api/channel", timeout=0.2)
        return True
    except httpx.HTTPError:
        return False


@pytest.fixture
def server(tmp_path):
    lp, ep = free_port(), free_port()
    out_path = tmp_path / "server-output.txt"
    with out_path.open("wb") as out:
        p = subprocess.Popen(
            [sys.executable, "-m", "app", "--root", str(tmp_path),
             "--local-port", str(lp), "--external-port", str(ep)],
            cwd=SERVER_DIR, stdout=out, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 10
            while not (_answers(lp) and _answers(ep)):
                if p.poll() is not None or time.monotonic() > deadline:
                    p.kill()
                    p.wait(10)
                    out.flush()
                    pytest.fail(
                        "server did not become ready; output:\n"
                        + out_path.read_text("utf-8", errors="replace")
                    )
                time.sleep(0.1)
            yield lp, ep, tmp_path
        finally:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(10)


def test_two_channels_live(server):
    lp, ep, _ = server
    assert httpx.get(f"http://127.0.0.1:{lp}/api/channel").json()["channel"] == "local"
    assert httpx.get(f"http://127.0.0.1:{ep}/api/channel").json()["channel"] == "external"
    r = httpx.get(f"http://127.0.0.1:{ep}/api/bootstrap")
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}


def test_dummy_otp_outbox_written(server):
    lp, _, root = server
    base = f"http://127.0.0.1:{lp}"
    httpx.post(f"{base}/api/bootstrap", json={"email": "a@x.com", "name": "a"})
    httpx.post(f"{base}/api/auth/otp/request", json={"email": "a@x.com"})
    outbox = root / "data" / "dev" / "otp-outbox.log"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if outbox.exists() and list((root / "logs").glob("*.jsonl")):
            break
        time.sleep(0.1)
    assert outbox.exists(), "otp outbox was not written within 5s"
    assert "a@x.com" in outbox.read_text("utf-8")
    assert list((root / "logs").glob("*.jsonl")), "no jsonl log within 5s"


@pytest.mark.skipif(sys.platform != "win32", reason="CTRL_BREAK_EVENT is Windows only")
def test_graceful_shutdown_stops_monitor(tmp_path):
    """serve() starts the monitor with the servers and stops it (then the log writer) on Ctrl+Break."""
    lp, ep = free_port(), free_port()
    out_path = tmp_path / "server-output.txt"
    with out_path.open("wb") as out:
        p = subprocess.Popen(
            [sys.executable, "-m", "app", "--root", str(tmp_path),
             "--local-port", str(lp), "--external-port", str(ep)],
            cwd=SERVER_DIR, stdout=out, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            deadline = time.monotonic() + 10
            while not (_answers(lp) and _answers(ep)):
                assert p.poll() is None and time.monotonic() < deadline, "server did not become ready"
                time.sleep(0.1)
            p.send_signal(signal.CTRL_BREAK_EVENT)
            code = p.wait(30)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait(10)
    output = out_path.read_text("utf-8", errors="replace")
    assert code == 0 and "Traceback" not in output, output
    events = [json.loads(line) for f in (tmp_path / "logs").glob("*.jsonl")
              for line in f.read_text("utf-8").splitlines()]
    monitor = [e["event"] for e in events if e["cat"] == "system" and e.get("event", "").startswith("monitor.")]
    assert monitor == ["monitor.start", "monitor.stop"]
