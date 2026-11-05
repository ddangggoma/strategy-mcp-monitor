"""Script runner (R20): a script error, a hang or an output flood never affects the main process.

`ScriptRunner.run` returns a `ScriptResult` for every outcome and never raises (except `CancelledError`).
Completion is the script process's exit, not pipe EOF: a script may leave a background child (e.g. an MCP launched
with Start-Process) that inherited the stdout/stderr pipes. Only a timeout kills, and then the whole process tree.
No Job Object is used, because a kill-on-close job would take the MCP a start script launched down with it.
"""

from __future__ import annotations

import asyncio
import codecs
import contextlib
import hashlib
import os
import subprocess
import time
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass
from pathlib import Path

import psutil

from app.monitor.models import ScriptStatus

MAX_TIMEOUT_SEC = 120
OUTPUT_CAP_BYTES = 1_048_576
DEFAULT_CONCURRENCY = 4
PIPE_DRAIN_SEC = 1.0
KILL_WAIT_SEC = 5.0

_CHUNK = 65_536
_EXTS = (".ps1", ".bat", ".cmd")

ScriptTarget = tuple[Path, str]  # (script path, expected sha256)


@dataclass(frozen=True)
class ScriptResult:
    status: ScriptStatus
    exit_code: int | None
    duration_ms: int
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    killed: int
    error: str | None  # missing | hash_mismatch | unsupported | spawn_failed | internal
    actual_sha256: str | None


def effective_timeout(requested: float) -> float:
    return max(1.0, min(requested, float(MAX_TIMEOUT_SEC)))


def _system32() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"


def build_argv(path: Path) -> list[str]:
    ext = path.suffix.lower()
    if ext == ".ps1":
        exe = _system32() / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        return [str(exe), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path)]
    if ext in (".bat", ".cmd"):
        return [str(_system32() / "cmd.exe"), "/d", "/c", str(path)]
    raise ValueError(f"unsupported script extension: {path.suffix!r}")


def decode_output(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("oem", errors="replace")


def _decode_capped(data: bytes, truncated: bool) -> str:
    if truncated:
        # The cap may cut a multi-byte UTF-8 character; drop the incomplete tail instead of falling back to OEM.
        try:
            return codecs.getincrementaldecoder("utf-8-sig")().decode(data, final=False)
        except UnicodeDecodeError:
            pass
    return decode_output(data)


def kill_tree(pid: int) -> int:
    """Kill `pid` and all its descendants (blocking). Returns how many of them ended; 0 if `pid` is already gone."""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return 0
    try:
        procs = [parent, *parent.children(recursive=True)]
    except psutil.Error:
        procs = [parent]  # the parent died meanwhile (or enumeration was denied): still kill what we have
    for p in procs:
        # Already gone, or access denied (then wait_procs counts it as alive).
        with contextlib.suppress(psutil.Error):
            p.kill()
    gone, _alive = psutil.wait_procs(procs, timeout=KILL_WAIT_SEC)
    return len(gone)


class _Capture:
    """Keeps the first OUTPUT_CAP_BYTES of a stream and keeps reading (discarding) the rest so the child never blocks."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.truncated = False

    async def pump(self, stream: asyncio.StreamReader) -> None:
        while chunk := await stream.read(_CHUNK):
            room = OUTPUT_CAP_BYTES - len(self.data)
            if room > 0:
                self.data += chunk[:room]
            if len(chunk) > room:
                self.truncated = True

    def text(self) -> str:
        return _decode_capped(bytes(self.data), self.truncated)


def _close_transport(proc: asyncio.subprocess.Process) -> None:
    # Private API (plan ruling, F14): the only way to release the pipe handles a background child may still hold.
    # Called only after the process has exited, so close() does not kill anything.
    transport = getattr(proc, "_transport", None)
    if transport is not None:
        transport.close()


class ScriptRunner:
    def __init__(self, concurrency: int = DEFAULT_CONCURRENCY) -> None:
        self._slots = asyncio.Semaphore(concurrency)
        self._locks: dict[Hashable, asyncio.Lock] = {}
        self._detached: set[asyncio.Task[None]] = set()
        self.active = 0
        self.peak_active = 0

    async def run(
        self,
        path: Path,
        *,
        expected_sha256: str,
        timeout_sec: float,
        env: Mapping[str, str],
        lock_key: Hashable,
        resolve: Callable[[], ScriptTarget | None] | None = None,
    ) -> ScriptResult:
        """Run ``path`` if its sha256 is ``expected_sha256``.

        ``resolve``, when given, is called once the per-MCP lock and a global slot are held, right
        before the hash check: its ``(path, expected_sha256)`` replaces the arguments (the script may
        have been edited while the run waited for a slot), and ``None`` means the script is gone.
        """
        started = time.perf_counter()
        try:
            lock = self._locks.setdefault(lock_key, asyncio.Lock())
            # MCP lock first: a run queued behind the same MCP must not hold a global slot while it waits.
            async with lock, self._slots:
                self.active += 1
                self.peak_active = max(self.peak_active, self.active)
                try:
                    if resolve is not None:
                        target = resolve()
                        if target is None:
                            return _failure("missing", started)
                        path, expected_sha256 = target
                    return await self._run(path, expected_sha256, timeout_sec, env)
                finally:
                    self.active -= 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # The exception text goes to stderr so the monitor can report it (a `system` log event).
            return _failure("internal", started, stderr=repr(exc))

    async def _run(
        self, path: Path, expected_sha256: str, timeout_sec: float, env: Mapping[str, str]
    ) -> ScriptResult:
        started = time.perf_counter()
        if path.suffix.lower() not in _EXTS:
            return _failure("unsupported", started)
        try:
            data = await asyncio.to_thread(path.read_bytes)
        except OSError:
            return _failure("missing", started)
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected_sha256.lower():
            return _failure("hash_mismatch", started, actual)

        argv = build_argv(path)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, **env},
                cwd=path.parent,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError:
            return _failure("spawn_failed", started, actual)

        assert proc.stdout is not None and proc.stderr is not None
        out, err = _Capture(), _Capture()
        readers = [asyncio.create_task(out.pump(proc.stdout)), asyncio.create_task(err.pump(proc.stderr))]
        try:
            killed = 0
            try:
                exit_code: int | None = await asyncio.wait_for(proc.wait(), effective_timeout(timeout_sec))
            except TimeoutError:
                killed = await asyncio.to_thread(kill_tree, proc.pid)
                exit_code = None
                try:
                    await asyncio.wait_for(proc.wait(), PIPE_DRAIN_SEC)
                except TimeoutError:
                    pass
            await _drain(readers)
        except BaseException:
            # Cancellation (service shutdown) or an internal error: stop waiting, never kill. The process keeps
            # running; a detached task finishes the cleanup once it exits on its own.
            self._detach(proc, readers)
            raise
        if proc.returncode is None:
            self._detach(proc, [])  # a timeout kill that did not take: close the transport once it does exit
        else:
            _close_transport(proc)

        if exit_code is None:
            status: ScriptStatus = "timeout"
        else:
            status = "ok" if exit_code == 0 else "failed"
        return ScriptResult(
            status=status,
            exit_code=exit_code,
            duration_ms=_ms_since(started),
            stdout=out.text(),
            stderr=err.text(),
            stdout_truncated=out.truncated,
            stderr_truncated=err.truncated,
            killed=killed,
            error=None,
            actual_sha256=actual,
        )

    def _detach(self, proc: asyncio.subprocess.Process, readers: list[asyncio.Task[None]]) -> None:
        task = asyncio.get_running_loop().create_task(_finish_detached(proc, readers))
        self._detached.add(task)
        task.add_done_callback(self._detached.discard)


async def _drain(readers: list[asyncio.Task[None]]) -> None:
    """Give the readers PIPE_DRAIN_SEC to reach EOF, then cancel the ones held open by a background child."""
    if not readers:
        return
    _done, pending = await asyncio.wait(readers, timeout=PIPE_DRAIN_SEC)
    for task in pending:
        task.cancel()
    # Collect every outcome (cancellation, a pipe error) so none is reported as "never retrieved".
    await asyncio.gather(*readers, return_exceptions=True)


async def _finish_detached(proc: asyncio.subprocess.Process, readers: list[asyncio.Task[None]]) -> None:
    try:
        with contextlib.suppress(Exception):
            await proc.wait()
            await _drain(readers)
    finally:
        for task in readers:
            task.cancel()
        # Still running only when cancelled at loop shutdown: closing the transport then would kill the script.
        if proc.returncode is not None:
            _close_transport(proc)


def _ms_since(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _failure(error: str, started: float, actual_sha256: str | None = None, stderr: str = "") -> ScriptResult:
    return ScriptResult(
        status="error",
        exit_code=None,
        duration_ms=_ms_since(started),
        stdout="",
        stderr=stderr,
        stdout_truncated=False,
        stderr_truncated=False,
        killed=0,
        error=error,
        actual_sha256=actual_sha256,
    )
