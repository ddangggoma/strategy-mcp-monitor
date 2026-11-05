from __future__ import annotations

import asyncio
import dataclasses
from collections import deque
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.monitor.models import CheckResult, Issue, Mcp, McpConfig
from app.monitor.probes import ProbeResult
from app.monitor.runner import ScriptResult


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class CapturingOtpProvider:
    """Test OTP provider that records (email, code) pairs instead of delivering."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, email: str, code: str) -> None:
        self.sent.append((email, code))


def make_mcp(id: int = 1, **config) -> Mcp:
    """Mcp fixture: 127.0.0.1:(9100 + id) named m<id>, unowned, created 2026-11-04T05:00Z."""
    fields = {"name": f"m{id}", "host": "127.0.0.1", "port": 9100 + id, **config}
    return Mcp(
        id=id,
        config=McpConfig.model_validate(fields),
        owner_id=None,
        created_by=None,
        created_at=datetime(2026, 11, 4, 5, 0, 0, tzinfo=UTC),
    )


def ok_result(**kw) -> ScriptResult:
    """A successful ScriptResult; keyword arguments override fields."""
    base = ScriptResult(
        status="ok", exit_code=0, duration_ms=10, stdout="", stderr="",
        stdout_truncated=False, stderr_truncated=False, killed=0, error=None, actual_sha256=None,
    )
    return dataclasses.replace(base, **kw)


@dataclass(frozen=True)
class RunCall:
    path: Path
    expected_sha256: str
    timeout_sec: float
    env: dict[str, str]
    lock_key: Hashable


class FakeRunner:
    """ScriptRunnerLike: records calls; returns queued results (ok when empty)."""

    def __init__(self) -> None:
        self.calls: list[RunCall] = []
        self.results: deque[ScriptResult] = deque()
        self.gate: asyncio.Event | None = None
        self.raise_next: Exception | None = None

    async def run(
        self,
        path: Path,
        *,
        expected_sha256: str,
        timeout_sec: float,
        env: Mapping[str, str],
        lock_key: Hashable,
        resolve: Callable[[], tuple[Path, str] | None] | None = None,
    ) -> ScriptResult:
        if resolve is not None:  # like the real runner: resolved "inside the slot", here at call time
            target = resolve()
            if target is not None:
                path, expected_sha256 = target
        self.calls.append(RunCall(Path(path), expected_sha256, timeout_sec, dict(env), lock_key))
        if self.raise_next is not None:
            exc, self.raise_next = self.raise_next, None
            raise exc
        if self.gate is not None:
            await self.gate.wait()
        return self.results.popleft() if self.results else ok_result()


class FakeProber:
    """ProberLike: probe ok (5.0 ms) and check healthy unless told otherwise."""

    def __init__(self, clock) -> None:
        self._clock = clock
        self._probes: dict[int, ProbeResult] = {}
        self._checks: dict[int, tuple[Issue | None, int | None, str | None]] = {}
        self.delay: float = 0.0
        self.probe_calls: list[int] = []
        self.check_calls: list[int] = []
        self.forgotten: list[int] = []
        self.closed = False

    def set_probe(self, mcp_id: int, result: ProbeResult) -> None:
        self._probes[mcp_id] = result

    def set_check(
        self, mcp_id: int, issue: Issue | None, pid: int | None = None, error: str | None = None
    ) -> None:
        self._checks[mcp_id] = (issue, pid, error)

    async def probe(self, mcp: Mcp) -> ProbeResult:
        self.probe_calls.append(mcp.id)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self._probes.get(mcp.id, ProbeResult(True, 5.0, None))

    async def check(self, mcp: Mcp) -> CheckResult:
        self.check_calls.append(mcp.id)
        if self.delay:
            await asyncio.sleep(self.delay)
        issue, pid, error = self._checks.get(mcp.id, (None, None, None))
        return CheckResult(
            at=self._clock.now(), issue=issue, latency_ms=5.0 if issue is None else None,
            pid=pid, process_name=None, error=error,
        )

    def forget(self, mcp_id: int) -> None:
        self.forgotten.append(mcp_id)

    async def aclose(self) -> None:
        self.closed = True
