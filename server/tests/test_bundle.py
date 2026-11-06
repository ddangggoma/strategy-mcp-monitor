# server/tests/test_bundle.py
"""Smoke tests of a built deployment bundle (``install/build.ps1``, Plan 5 Task 13).

Run with ``MCPMON_BUNDLE=<bundle folder> uv run python -m pytest -m bundle -v``. The install
scripts and ``docs/OPERATIONS.md`` are asserted by Tasks 14 and 16 (preflight F02).
"""

import json
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from app import __version__
from tests.live import free_port

pytestmark = pytest.mark.bundle
B = Path(os.environ.get("MCPMON_BUNDLE", "missing"))


def meta():
    return json.loads((B / "bundle.json").read_text("utf-8"))


def monitor_cmd():
    return [str(B / "bin" / "monitor" / "mcp-monitor.exe")] if meta()["layout"] == "pyinstaller" \
        else [str(B / "runtime" / "python.exe"), "-m", "app"]


def agent_cmd():
    return [str(B / "bin" / "agent" / "mcp-agent.exe")] if meta()["layout"] == "pyinstaller" \
        else [str(B / "runtime" / "python.exe"), "-m", "mcp_agent"]


def test_bundle_metadata_and_files():
    m = meta()
    assert set(m) == {"layout", "version", "python", "built_at", "commit"} and m["version"] == __version__
    assert m["layout"] in ("pyinstaller", "runtime") and m["python"].startswith("3.15.")
    for rel in ("web/board.html", "web/admin.html"):
        assert (B / rel).is_file(), rel
    assert not (B / "web" / ".vite").exists()


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


def test_bundle_agent_starts():
    p = subprocess.run([*agent_cmd(), "--help"], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert p.returncode == 0 and "--server" in p.stdout


def test_bundle_ignores_pythonpath(tmp_path):
    if meta()["layout"] == "runtime":
        env = {**os.environ, "PYTHONPATH": str(tmp_path / "evil")}
        p = subprocess.run([str(B / "runtime" / "python.exe"), "-c", "import sys; print(sys.path)"], capture_output=True,
                           text=True, timeout=60, env=env, stdin=subprocess.DEVNULL)
        assert p.returncode == 0 and "evil" not in p.stdout and "server" in p.stdout
    else:
        assert (B / "bin" / "monitor" / "_internal").is_dir() and (B / "bin" / "agent" / "_internal").is_dir()
        # W28: the frozen programs (SYSTEM for the monitor) never load code from PYTHONPATH or the cwd.
        evil = tmp_path / "evil"
        for pkg in ("app", "mcp_agent"):
            (evil / pkg).mkdir(parents=True)
            (evil / pkg / "__init__.py").write_text("raise SystemExit('EVIL package imported')", "utf-8")
        env = {**os.environ, "PYTHONPATH": str(evil)}
        for cmd, needle in (([*monitor_cmd(), "--version"], f"mcp-monitor {__version__}"), ([*agent_cmd(), "--help"], "--server")):
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env, cwd=evil, stdin=subprocess.DEVNULL)
            assert p.returncode == 0 and needle in p.stdout and "EVIL" not in p.stdout + p.stderr, cmd


def test_bundle_service_mode_needs_the_scm():
    # pywin32's servicemanager is in the bundle: outside the SCM, `service` ends with exit 2 (no admin needed).
    p = subprocess.run([*monitor_cmd(), "service"], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert p.returncode == 2 and "Service Control Manager" in p.stderr and "Traceback" not in p.stderr
