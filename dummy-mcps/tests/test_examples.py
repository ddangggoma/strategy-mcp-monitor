import os
import re
import subprocess
import sys
import time

import httpx
import psutil
import pytest

from tests.helpers import ROOT, free_port, listener_pid, rpc

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
PS = [os.path.expandvars(r"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"),
      "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]
SCRIPTS = {kind: ROOT / "examples" / f"{kind}.ps1" for kind in ("start", "stop", "restart")}
INIT = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}


@pytest.fixture
def env(tmp_path):
    port = free_port()
    e = {"MCP_ID": "901", "MCP_NAME": "calculator", "MCP_HOST": "127.0.0.1", "MCP_PORT": str(port),
         "DUMMY_MCPS_DIR": str(ROOT), "DUMMY_MCP_RUN_DIR": str(tmp_path), "DUMMY_MCP_CHAOS": "1"}
    yield e
    run_script("stop", e, tmp_path)


def run_script(kind, env, tmp_path):
    # Output goes to a file: with capture_output the background MCP inherits the pipe and EOF never arrives.
    with open(tmp_path / f"{kind}.txt", "wb") as out:
        return subprocess.run(PS + [str(SCRIPTS[kind])], env={**os.environ, **env},
                              stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, timeout=60)


def test_start_stop_cycle(env, tmp_path):
    port = int(env["MCP_PORT"])
    assert run_script("start", env, tmp_path).returncode == 0
    pid = int((tmp_path / "901.pid").read_text())
    assert listener_pid(port) == pid
    assert run_script("start", env, tmp_path).returncode == 0 and listener_pid(port) == pid
    assert run_script("stop", env, tmp_path).returncode == 0
    assert listener_pid(port) is None and not (tmp_path / "901.pid").exists()
    assert run_script("stop", env, tmp_path).returncode == 0


def test_restart_recovers_hung(env, tmp_path):
    port = int(env["MCP_PORT"])
    assert run_script("start", env, tmp_path).returncode == 0
    old = listener_pid(port)
    httpx.post(f"http://127.0.0.1:{port}/chaos/hang?sec=120")
    assert run_script("restart", env, tmp_path).returncode == 0
    assert listener_pid(port) not in (None, old)
    assert rpc(port, "initialize", INIT)[0]["result"]


@pytest.mark.parametrize("kind", ["start", "stop", "restart"])
@pytest.mark.parametrize("override", [{"MCP_NAME": "nope"}, {"DUMMY_MCPS_DIR": r"C:\does-not-exist"},
                                      {"MCP_PORT": "abc"}, {"MCP_ID": "../x"}])
def test_bad_environment_exit_2(env, tmp_path, kind, override):
    assert run_script(kind, {**env, **override}, tmp_path).returncode == 2


def test_start_after_crash_replaces_stale_pid_file(env, tmp_path):
    port = int(env["MCP_PORT"])
    assert run_script("start", env, tmp_path).returncode == 0
    httpx.post(f"http://127.0.0.1:{port}/chaos/crash")
    deadline = time.monotonic() + 10
    while listener_pid(port) is not None and time.monotonic() < deadline:
        time.sleep(0.1)
    assert listener_pid(port) is None
    assert (tmp_path / "901.pid").exists()  # a crash leaves the pid file behind
    assert run_script("start", env, tmp_path).returncode == 0
    assert listener_pid(port) == int((tmp_path / "901.pid").read_text())
    assert rpc(port, "initialize", INIT)[0]["result"]


def test_stop_does_not_kill_unrelated_process_named_in_stale_pid_file(env, tmp_path):
    """The pid file is only a hint: a recycled pid that is a live python must survive `stop`."""
    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        (tmp_path / "901.pid").write_text(str(bystander.pid))
        assert run_script("stop", env, tmp_path).returncode == 0
        assert bystander.poll() is None and psutil.pid_exists(bystander.pid)
        assert not (tmp_path / "901.pid").exists()  # stale file cleaned up
    finally:
        bystander.kill()
        bystander.wait(10)


def test_run_dir_with_spaces(env, tmp_path):
    run_dir = tmp_path / "run dir"
    e = {**env, "DUMMY_MCP_RUN_DIR": str(run_dir)}
    assert run_script("start", e, tmp_path).returncode == 0
    assert listener_pid(int(e["MCP_PORT"])) == int((run_dir / "901.pid").read_text())
    assert (run_dir / "901.out.log").exists() and (run_dir / "901.err.log").exists()
    assert run_script("stop", e, tmp_path).returncode == 0


# --- drift guard (Plan 2 F15): the three scripts deliberately duplicate logic; the shared parts must stay identical.

_SHARED = re.compile(r"^# >>> SHARED (\S+)\n(.*?)^# <<< SHARED \1\n", re.M | re.S)
_EXPECTED_BLOCKS = {
    "prelude": {"start", "stop", "restart"},
    "start-logic": {"start", "restart"},
    "stop-logic": {"stop", "restart"},
}


def _text(kind: str) -> str:
    return SCRIPTS[kind].read_bytes().decode("utf-8-sig").replace("\r\n", "\n")


def test_scripts_are_utf8_bom():
    for path in SCRIPTS.values():
        assert path.read_bytes().startswith(b"\xef\xbb\xbf"), path.name


def test_shared_blocks_identical_across_scripts():
    found: dict[str, dict[str, str]] = {}
    for kind in SCRIPTS:
        for name, body in _SHARED.findall(_text(kind)):
            assert kind not in found.setdefault(name, {}), f"{kind}.ps1 repeats block {name}"
            found[name][kind] = body
    assert {n: set(k) for n, k in found.items()} == _EXPECTED_BLOCKS
    for name, bodies in found.items():
        assert len(set(bodies.values())) == 1, f"block {name} drifted between {sorted(bodies)}"


def test_restart_is_self_contained():
    code = "\n".join(line for line in _text("restart").splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"\.ps1|\.cmd|\.bat", code)
    assert not re.search(r"^\s*[&.]\s", code, re.M)  # no call/dot-source of another script


def test_scripts_document_env_and_exit_codes():
    for kind in SCRIPTS:
        head = _text(kind).split("# >>> SHARED", 1)[0]
        for token in ("MCP_ID", "MCP_NAME", "MCP_HOST", "MCP_PORT", "DUMMY_MCPS_DIR", "DUMMY_MCP_RUN_DIR",
                      "DUMMY_MCP_CHAOS", "Exit codes"):
            assert token in head, f"{kind}.ps1 header lacks {token}"
