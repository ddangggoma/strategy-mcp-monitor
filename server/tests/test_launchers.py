import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.win.ffi import current_session_id
from app.win.launch import (
    LaunchError,
    LaunchSpec,
    LocalLauncher,
    NoLauncher,
    WtsLauncher,
    pick_launcher,
    running_as_system,
)

windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows API")

@windows
def test_local_launcher_refuses_another_session(tmp_path):
    with pytest.raises(LaunchError, match="session_mismatch"):
        LocalLauncher().launch(LaunchSpec(current_session_id() + 1, [sys.executable, "-c", "pass"], {}, tmp_path))

@windows
def test_local_launcher_runs_in_own_session_with_env(tmp_path):
    out = tmp_path / "o"
    code = "import os,time; open(os.environ['OUT'],'w').write(os.environ['MCPMON_AGENT_TOKEN']); time.sleep(30)"
    p = LocalLauncher().launch(LaunchSpec(current_session_id(), [sys.executable, "-c", code], {"OUT": str(out), "MCPMON_AGENT_TOKEN": "tok"}, tmp_path))
    try:
        deadline = time.monotonic() + 10
        while not out.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert out.read_text() == "tok" and p.poll() is None
    finally:
        p.kill()
    deadline = time.monotonic() + 5
    while p.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert p.poll() is not None

def test_wts_launcher_call_sequence():
    calls = []
    api = SimpleNamespace(
        query_user_token=lambda sid: calls.append(("token", sid)) or "tok",
        duplicate_token_ex=lambda tok: calls.append(("dup", tok)) or "primary",
        create_environment_block=lambda tok: calls.append(("env", tok)) or {"USERPROFILE": "C:\\Users\\hong", "PATH": "C:\\Windows"},
        create_process_as_user=lambda tok, cmdline, env, cwd, desktop: calls.append(("create", tok, cmdline, env, cwd, desktop)) or ("hproc", 777),
        get_exit_code=lambda h: 259, terminate=lambda h: calls.append(("kill", h)), close_handle=lambda h: None)
    spec = LaunchSpec(2, ["C:\\Py\\python.exe", "-m", "mcp_agent", "--server", "http://127.0.0.1:8700"], {"MCPMON_AGENT_TOKEN": "t"}, Path("C:/agent"))
    p = WtsLauncher(api).launch(spec)
    assert [c[0] for c in calls] == ["token", "dup", "env", "create"] and calls[0] == ("token", 2)
    _, tok, cmdline, env, cwd, desktop = calls[3]
    assert (tok, cmdline, cwd, desktop) == ("primary", "C:\\Py\\python.exe -m mcp_agent --server http://127.0.0.1:8700", str(Path("C:/agent")), "winsta0\\default")
    assert env == {"USERPROFILE": "C:\\Users\\hong", "PATH": "C:\\Windows", "MCPMON_AGENT_TOKEN": "t"}
    assert (p.pid, p.poll()) == (777, None)
    p.kill(); assert calls[-1] == ("kill", "hproc")

def test_wts_launcher_wraps_errors():
    api = SimpleNamespace(query_user_token=lambda sid: (_ for _ in ()).throw(OSError(1314, "privilege not held")))
    with pytest.raises(LaunchError, match="1314"):
        WtsLauncher(api).launch(LaunchSpec(2, ["x"], {}, Path(".")))

def test_pick_launcher():
    assert isinstance(pick_launcher("auto"), LocalLauncher)  # this dev PC never runs tests as SYSTEM
    assert isinstance(pick_launcher("none"), NoLauncher) and isinstance(pick_launcher("wts"), WtsLauncher)
    with pytest.raises(LaunchError, match="disabled"):
        NoLauncher().launch(LaunchSpec(1, ["x"], {}, Path(".")))


# --- beyond the plan's tests ---------------------------------------------------------------

def fake_wts_api(calls, *, exit_codes=(259,), create_error=None):
    codes = list(exit_codes)

    def create(tok, cmdline, env, cwd, desktop):
        if create_error is not None:
            raise create_error
        return ("hproc", 777)

    def exit_code(h):
        calls.append(("exit_code", h))
        return codes.pop(0) if len(codes) > 1 else codes[0]

    return SimpleNamespace(
        query_user_token=lambda sid: "tok", duplicate_token_ex=lambda tok: "primary",
        create_environment_block=lambda tok: {"PATH": "C:\\Windows", "MCPMON_AGENT_TOKEN": "user-set"},
        create_process_as_user=create, get_exit_code=exit_code,
        terminate=lambda h: calls.append(("kill", h)), close_handle=lambda h: calls.append(("close", h)))

def test_wts_launcher_closes_the_tokens_and_spec_env_wins():
    calls = []
    api = fake_wts_api(calls)
    seen = {}
    real_create = api.create_process_as_user
    api.create_process_as_user = lambda tok, cmdline, env, cwd, desktop: seen.update(env=env) or real_create(tok, cmdline, env, cwd, desktop)
    WtsLauncher(api).launch(LaunchSpec(2, ["x"], {"MCPMON_AGENT_TOKEN": "t"}, Path(".")))
    assert seen["env"]["MCPMON_AGENT_TOKEN"] == "t"
    assert sorted(c[1] for c in calls if c[0] == "close") == ["primary", "tok"]

def test_wts_launcher_create_failure_closes_tokens_and_raises():
    calls = []
    with pytest.raises(LaunchError, match="1314"):
        WtsLauncher(fake_wts_api(calls, create_error=OSError(1314, "x"))).launch(LaunchSpec(2, ["x"], {}, Path(".")))
    assert sorted(c[1] for c in calls if c[0] == "close") == ["primary", "tok"]

def test_wts_process_keeps_the_exit_code_and_closes_its_handle_once():
    calls = []
    p = WtsLauncher(fake_wts_api(calls, exit_codes=(259, 3))).launch(LaunchSpec(2, ["x"], {}, Path(".")))
    assert p.poll() is None and p.poll() == 3 and p.poll() == 3
    assert [c for c in calls if c[0] == "close" and c[1] == "hproc"] == [("close", "hproc")]
    assert len([c for c in calls if c[0] == "exit_code"]) == 2
    p.kill()
    assert ("kill", "hproc") not in calls  # an exited process is not terminated

def test_wts_terminate_error_is_swallowed():
    def boom(h):
        raise OSError(5, "denied")
    api = fake_wts_api([])
    api.terminate = boom
    WtsLauncher(api).launch(LaunchSpec(2, ["x"], {}, Path("."))).kill()

@windows
def test_local_launcher_wraps_spawn_errors(tmp_path):
    with pytest.raises(LaunchError, match="FileNotFoundError"):
        LocalLauncher().launch(LaunchSpec(current_session_id(), [str(tmp_path / "missing.exe")], {}, tmp_path))

def test_local_launcher_names():
    assert (LocalLauncher.name, WtsLauncher.name, NoLauncher.name) == ("local", "wts", "none")

@windows
def test_this_dev_pc_does_not_run_as_system():
    assert running_as_system() is False and os.environ.get("USERNAME", "").upper() != "SYSTEM"


@windows
@pytest.mark.integration
async def test_supervisor_launches_a_real_stdlib_agent_and_stop_kills_it(services, clock, tmp_path, monkeypatch):
    """F07/F08 with real processes: the base interpreter runs ``-m mcp_agent`` from ``agent_dir``
    (via ``PYTHONPATH``), the launched pid is the agent's own pid, and ``stop`` leaves nothing behind."""
    import psutil

    from app.activity.agent_supervisor import AgentOptions, AgentSupervisor
    from tests.session_helpers import snap, ws
    from tests.test_auth_api import audit_events
    from tests.winfakes import eventually

    pkg = tmp_path / "agent" / "mcp_agent"; pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", "utf-8")
    (pkg / "__main__.py").write_text(
        "import os, sys, time\n"
        "open(os.path.join(os.environ['OUT_DIR'], 'started'), 'w').write(f\"{os.getpid()} {' '.join(sys.argv[1:])}\")\n"
        "time.sleep(60)\n", "utf-8")
    monkeypatch.setenv("OUT_DIR", str(tmp_path))
    s = AgentSupervisor(services.agents, LocalLauncher(), services.rdp, services.tamper, services.log, clock,
                        AgentOptions(agent_dir=tmp_path / "agent", stop_grace_sec=0.2))
    services.rdp.add_listener(s.on_session_change)
    services.rdp.apply(snap(clock.now(), ws(current_session_id())))
    started = tmp_path / "started"
    try:
        await eventually(lambda: started.exists() and started.read_text("utf-8").strip() != "", timeout=15)
        pid_text, args = started.read_text("utf-8").split(" ", 1)
        assert args == "--server http://127.0.0.1:8700 --dialog edge"
        [launched] = [e for e in await audit_events(services, "system") if e.get("event") == "agent.launched"]
        assert (launched["pid"], launched["launcher"]) == (int(pid_text), "local")  # no venv redirector (F08)
    finally:
        await s.stop()
    await eventually(lambda: not psutil.pid_exists(int(pid_text)), timeout=10)
