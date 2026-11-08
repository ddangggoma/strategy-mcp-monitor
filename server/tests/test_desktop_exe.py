"""The release mcp-monitor.exe built by install/build-desktop.ps1 (Plan 6 Task 13).

Run with ``$env:MCPMON_DESKTOP_EXE = "<repo>\\dist\\mcp-monitor-1.0.0.exe"; uv run python -m pytest -m desktop -v``.
Nothing here needs admin rights or changes this PC (install without admin stops at require_admin). On an elevated
shell (the GitHub runner) the real install would run, so that test skips there with its reason.
"""
import ctypes
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from app import __version__
from tests.live import scratch_path  # noqa: F401 (the tmp_path fixture: a scratch folder a data root may sit in)

pytestmark = pytest.mark.desktop
EXE = Path(os.environ.get("MCPMON_DESKTOP_EXE", "missing"))


@pytest.fixture(autouse=True)
def release_exe():
    if "MCPMON_DESKTOP_EXE" not in os.environ:
        pytest.skip("set MCPMON_DESKTOP_EXE to the release exe from install\\build-desktop.ps1")
    if not EXE.is_file():
        pytest.fail(f"MCPMON_DESKTOP_EXE={EXE} is not a file")


def run(*args, timeout=120):
    return subprocess.run([str(EXE), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, stdin=subprocess.DEVNULL)


def test_version_is_a_release_build_and_the_sha256_file_matches():
    p = run("--version")
    assert p.returncode == 0, p.stderr
    assert re.fullmatch(rf"mcp-monitor {re.escape(__version__)} \(payload [0-9a-f]{{12}}, release\)", p.stdout.strip()), p.stdout
    digest = hashlib.sha256(EXE.read_bytes()).hexdigest()
    assert (EXE.parent / f"{EXE.name}.sha256").read_bytes() == f"{digest}  {EXE.name}\n".encode("ascii")


def test_verify_payload_runs_the_embedded_server(tmp_path):
    p = run("verify-payload", str(tmp_path / "v"))
    assert p.returncode == 0 and p.stdout.startswith("payload OK: "), p.stdout + p.stderr
    root = tmp_path / "v" / "payload"
    v = subprocess.run([str(root / "bin" / "monitor" / "mcp-monitor-server.exe"), "--version"], capture_output=True, text=True,
                       timeout=60, stdin=subprocess.DEVNULL)
    assert v.returncode == 0 and v.stdout.strip() == f"mcp-monitor {__version__}"
    meta = json.loads((root / "bundle.json").read_text("utf-8"))
    assert (meta["layout"], meta["agent"], meta["version"]) == ("pyinstaller", "desktop", __version__)
    assert re.fullmatch(r"[0-9a-f]{40}", meta["commit"]) and meta["built_at"] != "fixture", meta
    assert not (root / "install").exists() and not (root / "bin" / "agent").exists()


def test_dry_run_plans_from_the_release_payload(tmp_path):
    p = run("install", "--dry-run", "--install-dir", str(tmp_path / "i"), "--data-root", str(tmp_path / "d"))
    assert p.returncode == 0, p.stderr
    plan = json.loads(p.stdout)
    assert (plan["version"], plan["layout"], plan["steps"][0]["id"]) == (__version__, "pyinstaller", "require_admin")


def test_install_without_admin_changes_nothing(tmp_path):
    if ctypes.windll.shell32.IsUserAnAdmin():
        pytest.skip("elevated shell (the GitHub runner): a real install would run; the release job checks it as a "
                    "throw-away standard user (standard-user-tests.ps1 -ReleaseExe) and P8 on a standard account")
    p = run("install", "--install-dir", str(tmp_path / "i"), "--data-root", str(tmp_path / "d"))
    assert p.returncode == 1 and "관리자 권한으로 다시 실행하세요" in p.stdout, p.stdout + p.stderr
    assert not any((tmp_path / n).exists() for n in ("i", "d", "i.staging"))
