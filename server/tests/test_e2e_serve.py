import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
