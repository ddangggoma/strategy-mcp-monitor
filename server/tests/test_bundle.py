# server/tests/test_bundle.py
"""Smoke tests of a built payload (``install/build.ps1``; Plan 5 Task 13, Plan 6 Task 2).

Run with ``MCPMON_BUNDLE=<repo>\\dist\\payload uv run python -m pytest -m bundle -v``. The payload is
what ``mcp-monitor.exe`` embeds (Plan 6): the server, the web app and the operations guide. The
desktop agent is ``mcp-monitor.exe agent`` itself, tested with ``-m desktop`` (Task 13).
"""

import json
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from app import __version__
from tests.live import free_port, scratch_path  # noqa: F401 (the tmp_path fixture: a scratch folder a data root may sit in)

pytestmark = pytest.mark.bundle
B = Path(os.environ.get("MCPMON_BUNDLE", "missing"))


def meta():
    return json.loads((B / "bundle.json").read_text("utf-8"))


def monitor_cmd():
    return [str(B / "bin" / "monitor" / "mcp-monitor-server.exe")]


def test_bundle_metadata_and_files():
    raw = (B / "bundle.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")  # UTF-8 without a BOM
    m = meta()
    assert set(m) == {"layout", "version", "python", "built_at", "commit", "agent"} and m["version"] == __version__
    assert (m["layout"], m["agent"]) == ("pyinstaller", "desktop") and m["python"].startswith("3.15.")
    for rel in ("web/board.html", "web/admin.html", "web/notice.html", "bin/monitor/mcp-monitor-server.exe"):
        assert (B / rel).is_file(), rel
    assert not (B / "web" / ".vite").exists()
    assert not (B / "install").exists() and not (B / "bin" / "agent").exists()
    assert not (B / ".partial").exists() and not (B / "bin" / "monitor" / "mcp-monitor.exe").exists()
    # The operations guide ships as the repo has it (a stale payload fails here: rebuild it).
    ops = Path(__file__).resolve().parents[2] / "docs" / "ops" / "OPERATIONS.md"
    assert (B / "docs" / "OPERATIONS.md").read_bytes() == ops.read_bytes()


def test_bundle_version():
    p = subprocess.run([*monitor_cmd(), "--version"], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert p.returncode == 0 and p.stdout.strip() == f"mcp-monitor {__version__}"


def test_bundle_serves_the_built_board(tmp_path):
    lp, ep = free_port(), free_port(); assert lp != ep
    # No real session collection (preflight F08): no WTS polling, event log or agent launches.
    p = subprocess.Popen([*monitor_cmd(), "--root", str(tmp_path), "--local-port", str(lp), "--external-port", str(ep),
                          "--external-host", "127.0.0.1", "--session-source", "none"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                if httpx.get(f"http://127.0.0.1:{lp}/api/channel", timeout=0.5).json()["channel"] == "local": break
            except httpx.HTTPError:
                pass
            assert p.poll() is None and time.monotonic() < deadline
            time.sleep(0.2)
        r = httpx.get(f"http://127.0.0.1:{ep}/")
        assert r.status_code == 200 and r.text == (B / "web" / "board.html").read_text("utf-8")
    finally:
        p.terminate(); p.wait(15)


def test_bundle_server_picks_the_desktop_agent():
    # The frozen server reads its own bundle.json: the agent is mcp-monitor.exe agent, the notice a WebView2 window.
    p = subprocess.run([*monitor_cmd(), "--agent-dialog", "edge"], capture_output=True, text=True, timeout=60,
                       stdin=subprocess.DEVNULL)
    assert p.returncode == 2 and "--agent-dialog edge is not available in a desktop bundle" in p.stderr
    h = subprocess.run([*monitor_cmd(), "--help"], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert h.returncode == 0 and "webview" in h.stdout


def test_bundle_ignores_pythonpath(tmp_path):
    assert (B / "bin" / "monitor" / "_internal").is_dir()
    # W28: the frozen server (SYSTEM) never loads code from PYTHONPATH or the cwd.
    evil = tmp_path / "evil"
    (evil / "app").mkdir(parents=True)
    (evil / "app" / "__init__.py").write_text("raise SystemExit('EVIL package imported')", "utf-8")
    env = {**os.environ, "PYTHONPATH": str(evil)}
    p = subprocess.run([*monitor_cmd(), "--version"], capture_output=True, text=True, timeout=60, env=env, cwd=evil,
                       stdin=subprocess.DEVNULL)
    assert p.returncode == 0 and f"mcp-monitor {__version__}" in p.stdout and "EVIL" not in p.stdout + p.stderr


def test_bundle_service_mode_needs_the_scm():
    # pywin32's servicemanager is in the bundle: outside the SCM, `service` ends with exit 2 (no admin needed).
    p = subprocess.run([*monitor_cmd(), "service"], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert p.returncode == 2 and "Service Control Manager" in p.stderr and "Traceback" not in p.stderr
