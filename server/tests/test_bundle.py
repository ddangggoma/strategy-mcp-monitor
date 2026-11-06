# server/tests/test_bundle.py
"""Smoke tests of a built deployment bundle (``install/build.ps1``, Plan 5 Task 13).

Run with ``MCPMON_BUNDLE=<bundle folder> uv run python -m pytest -m bundle -v``. The install
scripts are asserted here since Task 14; ``docs/OPERATIONS.md`` is asserted by Task 16 (preflight F02).
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
from tests.test_install_scripts import ps

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
    for name in ("install.ps1", "uninstall.ps1", "audit-policy.ps1"):
        assert (B / "install" / name).read_bytes().startswith(b"\xef\xbb\xbf"), name  # UTF-8 with BOM (PowerShell 5.1)
    # The operations guide ships as the repo has it (a stale bundle fails here: rebuild it).
    ops = Path(__file__).resolve().parents[2] / "docs" / "ops" / "OPERATIONS.md"
    assert (B / "docs" / "OPERATIONS.md").read_bytes() == ops.read_bytes()


def test_bundle_install_scripts_plan_from_the_bundle(tmp_path):
    # Run from the bundle with no -Source: the bundle is the script's parent folder (DryRun only, no admin).
    inst, data = tmp_path / "i", tmp_path / "d"
    p = ps("-File", str(B / "install" / "install.ps1"), "-DryRun", "-InstallDir", str(inst), "-DataRoot", str(data))
    assert p.returncode == 0, p.stdout + p.stderr
    plan = json.loads(p.stdout)
    assert (plan["layout"], plan["version"]) == (meta()["layout"], __version__)
    steps = {s["id"]: s for s in plan["steps"]}
    assert steps["copy_bundle"]["args"][:2] == [str(B.resolve()), str(inst)]
    svc = steps["service_install"]["args"]
    program = svc[svc.index("binPath=") + 1].split('"')[1]
    # The service runs the bundle's own monitor program, copied to the same place under the install folder.
    assert program.startswith(str(inst) + "\\") and (B / Path(program).relative_to(inst)).is_file()
    assert svc[svc.index("binPath=") + 1].endswith(f'service --root "{data}" --local-port 8700 --external-port 8701')
    for script, args in (("uninstall.ps1", ["-InstallDir", str(inst), "-DataRoot", str(data)]), ("audit-policy.ps1", ["-Enable", "-DataRoot", str(data)])):
        p = ps("-File", str(B / "install" / script), "-DryRun", *args)
        assert p.returncode == 0 and json.loads(p.stdout)["steps"][0]["id"] == "require_admin", p.stdout + p.stderr
    assert json.loads(p.stdout)["version"] == __version__  # audit-policy.ps1 reads the bundle it sits in


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
