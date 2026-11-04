import asyncio
import hashlib
import subprocess
import sys
import time
import tracemalloc
import uuid
from pathlib import Path

import psutil
import pytest

import app.monitor.runner as runner_mod
from app.monitor.runner import ScriptRunner, build_argv, decode_output, effective_timeout, kill_tree

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
ENV = {"PYTHON": sys.executable, "MCP_ID": "7", "MCP_NAME": "calc", "MCP_TRIGGER": "auto"}


def write(tmp_path, name, text, bom=False):
    data = (b"\xef\xbb\xbf" if bom else b"") + text.replace("\n", "\r\n").encode("utf-8")
    p = tmp_path / name; p.write_bytes(data); return p, hashlib.sha256(data).hexdigest()


async def run(runner, p, sha, timeout=10, key=1):
    return await runner.run(p, expected_sha256=sha, timeout_sec=timeout, env=ENV, lock_key=key)


def marker_alive(marker):
    return any(marker in " ".join(pr.info["cmdline"] or []) for pr in psutil.process_iter(["cmdline"]))


def kill_marker(marker):
    for pr in psutil.process_iter(["cmdline"]):
        if marker in " ".join(pr.info["cmdline"] or []): pr.kill()


def last_arg_alive(marker):
    """A process whose final argument is exactly `marker` (does not match a parent that merely mentions it)."""
    return any((pr.info["cmdline"] or [""])[-1] == marker for pr in psutil.process_iter(["cmdline"]))


async def wait_detached(runner, limit=15):
    deadline = time.perf_counter() + limit
    while runner._detached and time.perf_counter() < deadline:
        await asyncio.sleep(0.05)
    assert not runner._detached


async def test_bat_ok_with_env(tmp_path):
    p, sha = write(tmp_path, "start.bat", "@echo off\necho %MCP_ID% %MCP_TRIGGER%\nexit /b 0")
    r = await run(ScriptRunner(), p, sha)
    assert (r.status, r.exit_code, r.killed, r.error) == ("ok", 0, 0, None) and "7 auto" in r.stdout
    assert r.actual_sha256 == sha and r.stdout_truncated is False and r.stderr_truncated is False


async def test_ps1_korean_output(tmp_path):
    try: "시작".encode("oem")
    except UnicodeEncodeError: pytest.skip("OEM code page cannot encode Korean")
    p, sha = write(tmp_path, "start.ps1", "Write-Output \"$env:MCP_NAME 시작\"\nexit 0", bom=True)
    r = await run(ScriptRunner(), p, sha)
    assert r.status == "ok" and "calc 시작" in r.stdout


async def test_failed_exit_code(tmp_path):
    p, sha = write(tmp_path, "stop.bat", "@echo off\necho bad 1>&2\nexit /b 3")
    r = await run(ScriptRunner(), p, sha)
    assert (r.status, r.exit_code) == ("failed", 3) and "bad" in r.stderr


async def test_ps1_failed_exit_code(tmp_path):
    p, sha = write(tmp_path, "stop.ps1", "[Console]::Error.WriteLine('nope')\nexit 5")
    r = await run(ScriptRunner(), p, sha)
    assert (r.status, r.exit_code, r.error) == ("failed", 5, None) and "nope" in r.stderr


async def test_missing_and_unsupported(tmp_path):
    r = await run(ScriptRunner(), tmp_path / "nope.bat", "0" * 64)
    assert (r.status, r.error, r.exit_code) == ("error", "missing", None)
    p, sha = write(tmp_path, "x.py", "print(1)")
    assert (await run(ScriptRunner(), p, sha)).error == "unsupported"


async def test_hash_mismatch_does_not_execute(tmp_path):
    flag = tmp_path / "ran.txt"
    p, sha = write(tmp_path, "start.bat", f"@echo off\necho x > \"{flag}\"")
    r = await run(ScriptRunner(), p, "0" * 64)
    assert (r.status, r.error, r.actual_sha256) == ("error", "hash_mismatch", sha) and not flag.exists()


async def test_timeout_kills_tree(tmp_path):
    marker = uuid.uuid4().hex
    p, sha = write(tmp_path, "start.bat", f'@echo off\nstart "" /b "%PYTHON%" -c "import time; time.sleep(60)" {marker}\nping -n 60 127.0.0.1 >nul')
    t = time.perf_counter(); r = await run(ScriptRunner(), p, sha, timeout=2)
    assert r.status == "timeout" and r.exit_code is None and r.killed >= 2
    assert time.perf_counter() - t < 8 and not marker_alive(marker)


async def test_timeout_kills_grandchild(tmp_path):
    child, grandchild = uuid.uuid4().hex, uuid.uuid4().hex
    code = (f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', '{grandchild}']);"
            " time.sleep(60)")
    p, sha = write(tmp_path, "start.bat", f'@echo off\n"%PYTHON%" -c "{code}" {child}')
    try:
        task = asyncio.create_task(run(ScriptRunner(), p, sha, timeout=4))
        deadline = time.perf_counter() + 6
        while not last_arg_alive(grandchild) and time.perf_counter() < deadline:
            await asyncio.sleep(0.1)
        assert last_arg_alive(grandchild), "grandchild never started"
        r = await task
        assert r.status == "timeout" and r.killed >= 3
        assert not last_arg_alive(child) and not last_arg_alive(grandchild)
    finally:
        kill_marker(child); kill_marker(grandchild)


async def test_event_loop_stays_responsive_while_script_hangs(tmp_path):
    p, sha = write(tmp_path, "start.bat", "@echo off\nping -n 60 127.0.0.1 >nul")
    gaps, stop = [], asyncio.Event()

    async def tick():
        last = time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(0.05)
            now = time.perf_counter(); gaps.append(now - last); last = now

    ticker = asyncio.create_task(tick())
    r = await run(ScriptRunner(), p, sha, timeout=2)
    stop.set(); await ticker
    assert r.status == "timeout"
    assert len(gaps) >= 20 and max(gaps) < 0.5


async def test_output_capped(tmp_path):
    p, sha = write(tmp_path, "start.bat", '@echo off\n"%PYTHON%" -c "import sys; sys.stdout.write(\'x\' * 5_000_000)"')
    r = await run(ScriptRunner(), p, sha, timeout=30)
    assert r.status == "ok" and len(r.stdout.encode()) == 1_048_576 and r.stdout_truncated is True


async def test_output_flood_memory_bounded(tmp_path):
    code = "import sys; [(sys.stdout.buffer.write(b'y' * 1_000_000), sys.stderr.buffer.write(b'z' * 1_000_000)) for _ in range(30)]"
    p, sha = write(tmp_path, "start.bat", f'@echo off\n"%PYTHON%" -c "{code}"')
    tracemalloc.start()
    try:
        r = await run(ScriptRunner(), p, sha, timeout=60)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert r.status == "ok" and r.stdout_truncated and r.stderr_truncated
    assert (len(r.stdout), len(r.stderr)) == (1_048_576, 1_048_576) and set(r.stdout) == {"y"}
    assert peak < 16 * 1_048_576  # 60 MB went through the pipes


async def test_truncated_utf8_tail_is_not_decoded_as_oem(tmp_path):
    # 3-byte characters: the 1 MiB cut lands inside a character; the prefix must still decode as UTF-8.
    p, sha = write(tmp_path, "start.bat", '@echo off\n"%PYTHON%" -c "import sys; sys.stdout.buffer.write(\'\\uac00\'.encode() * 500_000)"')
    r = await run(ScriptRunner(), p, sha, timeout=30)
    assert r.status == "ok" and r.stdout_truncated is True
    assert r.stdout == "\uac00" * (1_048_576 // 3)


async def test_background_child_holding_pipe_does_not_block(tmp_path):
    marker = uuid.uuid4().hex
    p, sha = write(tmp_path, "start.bat", f'@echo off\nstart "" /b "%PYTHON%" -c "import time; time.sleep(30)" {marker}\nexit /b 0')
    try:
        r = await run(ScriptRunner(), p, sha)
        assert r.status == "ok" and r.killed == 0 and r.duration_ms < 5000
        assert marker_alive(marker)
    finally:
        kill_marker(marker)


async def test_ps1_start_process_child_survives(tmp_path):
    # Same launch shape as dummy-mcps/examples/start.ps1: the redirected Start-Process child inherits the pipes.
    marker = uuid.uuid4().hex
    text = (
        f"$out = Join-Path $PSScriptRoot 'child.out.log'; $err = Join-Path $PSScriptRoot 'child.err.log'\n"
        f"$p = Start-Process -FilePath $env:PYTHON -ArgumentList '-c','\"import time; time.sleep(30)\"','{marker}'"
        " -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru\n"
        "Write-Output \"started $($p.Id)\"\nexit 0"
    )
    p, sha = write(tmp_path, "start.ps1", text, bom=True)
    try:
        t = time.perf_counter(); r = await run(ScriptRunner(), p, sha, timeout=30)
        assert (r.status, r.exit_code, r.killed) == ("ok", 0, 0) and "started" in r.stdout
        assert time.perf_counter() - t < 10
        assert marker_alive(marker)
    finally:
        kill_marker(marker)


async def test_per_key_lock_and_global_cap(tmp_path):
    p, sha = write(tmp_path, "s.bat", "@echo off\nping -n 2 127.0.0.1 >nul")
    runner = ScriptRunner(concurrency=4)
    await asyncio.gather(run(runner, p, sha, key=1), run(runner, p, sha, key=1))
    assert runner.peak_active == 1
    runner.peak_active = 0
    rs = await asyncio.gather(*(run(runner, p, sha, key=k) for k in range(6)))
    assert runner.peak_active == 4 and all(r.status == "ok" for r in rs)
    assert runner.active == 0


async def test_waiting_on_mcp_lock_does_not_hold_a_global_slot(tmp_path):
    slow, slow_sha = write(tmp_path, "slow.bat", "@echo off\nping -n 3 127.0.0.1 >nul")
    fast, fast_sha = write(tmp_path, "fast.bat", "@echo off\nexit /b 0")
    runner = ScriptRunner(concurrency=2)
    first = asyncio.create_task(run(runner, slow, slow_sha, key="a"))
    await asyncio.sleep(0.3)
    queued = [asyncio.create_task(run(runner, slow, slow_sha, key="a")) for _ in range(2)]
    await asyncio.sleep(0.3)
    t = time.perf_counter(); r = await run(runner, fast, fast_sha, key="b")
    assert r.status == "ok" and time.perf_counter() - t < 1.5  # did not wait behind the "a" queue
    await asyncio.gather(first, *queued)


async def test_spawn_failure_is_result(tmp_path, monkeypatch):
    p, sha = write(tmp_path, "start.bat", "exit /b 0")
    async def boom(*a, **k): raise PermissionError("denied")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    r = await run(ScriptRunner(), p, sha)
    assert (r.status, r.error) == ("error", "spawn_failed")


async def test_internal_error_before_spawn_is_result(tmp_path, monkeypatch):
    p, sha = write(tmp_path, "start.bat", "@echo off\nexit /b 0")
    def boom(path): raise RuntimeError("bug")
    monkeypatch.setattr(runner_mod, "build_argv", boom)
    runner = ScriptRunner()
    r = await run(runner, p, sha)
    assert (r.status, r.error, r.exit_code) == ("error", "internal", None) and runner.active == 0
    assert r.stderr == "RuntimeError('bug')"  # the detail the monitor logs as a system event
    monkeypatch.undo()
    assert (await run(runner, p, sha)).status == "ok"  # lock and slot were released


async def test_internal_error_after_spawn_is_result(tmp_path, monkeypatch):
    flag = tmp_path / "done.txt"
    p, sha = write(tmp_path, "start.bat", f'@echo off\nping -n 3 127.0.0.1 >nul\necho done > "{flag}"')
    def boom(pid): raise RuntimeError("bug")
    monkeypatch.setattr(runner_mod, "kill_tree", boom)
    runner = ScriptRunner()
    r = await run(runner, p, sha, timeout=1)
    assert (r.status, r.error) == ("error", "internal") and runner.active == 0
    await wait_detached(runner)  # the script was not killed: it finishes on its own and the transport is closed
    assert flag.exists()


async def test_cancel_stops_waiting_without_killing(tmp_path):
    flag = tmp_path / "done.txt"
    p, sha = write(tmp_path, "start.bat", f'@echo off\nping -n 3 127.0.0.1 >nul\necho done > "{flag}"')
    runner = ScriptRunner()
    task = asyncio.create_task(run(runner, p, sha))
    await asyncio.sleep(0.8)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runner.active == 0 and not flag.exists()
    await wait_detached(runner)
    assert flag.exists()


def test_kill_tree_of_gone_process_is_zero():
    gone = subprocess.Popen([sys.executable, "-c", "pass"]); gone.wait()
    assert kill_tree(gone.pid) == 0


def test_effective_timeout_and_argv():
    assert (effective_timeout(300), effective_timeout(30)) == (120.0, 30.0)
    assert effective_timeout(0) == 1.0
    ps = build_argv(Path(r"C:\s\start.ps1"))
    assert ps[0].lower().endswith(r"windowspowershell\v1.0\powershell.exe")
    assert ps[1:] == ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", r"C:\s\start.ps1"]
    assert build_argv(Path(r"C:\s\stop.cmd"))[1:] == ["/d", "/c", r"C:\s\stop.cmd"]
    bat = build_argv(Path(r"C:\s\stop.BAT"))
    assert bat[0].lower().endswith(r"system32\cmd.exe") and Path(bat[0]).is_absolute()
    with pytest.raises(ValueError):
        build_argv(Path(r"C:\s\x.py"))


def test_decode_output():
    assert decode_output(b"\xef\xbb\xbfok") == "ok"
    assert decode_output("한글".encode("utf-8")) == "한글"


def test_decode_output_oem_fallback():
    try: data = "가나".encode("oem")
    except UnicodeEncodeError: pytest.skip("OEM code page cannot encode Korean")
    assert decode_output(data) == "가나"
    assert decode_output(b"\xff\xfe ok") == b"\xff\xfe ok".decode("oem", errors="replace")
