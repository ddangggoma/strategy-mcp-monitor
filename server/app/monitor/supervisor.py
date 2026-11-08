"""Monitor: runs the ping / issue-check / confirm / housekeeping loops and executes engine effects.

Everything here runs on the event-loop thread (LogWriter.emit, BoardBus and McpHistory require it).
Rounds only spawn tasks and return at once; a probe may take the whole probe timeout (a refused
loopback connect alone takes ~2 s on Windows) without delaying any loop. Each MCP has one in-flight
ping and one in-flight check at most, with separate guards, so a hung ping never holds back the 1 s
confirm check (ruling F6). Script runs are tasks too, so a slow script never blocks the loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Hashable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from app.activity.tamper import TamperMonitor
from app.clock import Clock, to_kst_iso
from app.logstore.writer import LogWriter
from app.monitor.bus import BoardBus
from app.monitor.engine import (
    ActionInProgressError,
    Alert,
    Effect,
    McpEngine,
    RunScript,
    Transition,
)
from app.monitor.history import ActionRecord, McpHistory, TransitionRecord
from app.monitor.icon_images import IconImageStore
from app.monitor.models import ActionKind, CheckResult, Mcp, McpState, ScriptStatus
from app.monitor.probes import ProbeResult
from app.monitor.runner import PIPE_DRAIN_SEC, ScriptResult, ScriptTarget
from app.monitor.scripts import ScriptInfo, ScriptStore
from app.monitor.store import McpNotFoundError, McpStore
from app.settings.store import Settings, SettingsStore
from app.users.store import User

LOG_OUTPUT_CHARS = 4096
HOUSEKEEP_INTERVAL_SEC = 60.0
PURGE_EVERY = 60  # housekeeping rounds (hourly)
PORT_LOOKUP_LOG_EVERY = timedelta(minutes=10)
DEFAULT_GRACE_SEC = 10.0
BATCH_ITEM_TTL_SEC = 1.0  # = the SSE coalesce period: time-derived fields stay this fresh


class ScriptRunnerLike(Protocol):
    async def run(
        self,
        path: Path,
        *,
        expected_sha256: str,
        timeout_sec: float,
        env: Mapping[str, str],
        lock_key: Hashable,
        resolve: Callable[[], ScriptTarget | None] | None = None,
    ) -> ScriptResult: ...

    async def kill_all(self) -> int: ...

    async def aclose(self) -> None: ...


_SAFE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+", re.ASCII)


def safe_actor(user: User | None) -> str:
    """``MCP_ACTOR`` for a script (W37): ``"system"``, the email when it holds no cmd syntax, else
    ``user-<id>``. cmd parses a line after expanding ``%MCP_ACTOR%``, so an email with ``&`` (which
    the user store allows) could otherwise run a command as SYSTEM."""
    if user is None:
        return "system"
    if _SAFE_EMAIL.fullmatch(user.email):
        return user.email
    return f"user-{user.id}"


class ProberLike(Protocol):
    async def probe(self, mcp: Mcp) -> ProbeResult: ...

    async def check(self, mcp: Mcp) -> CheckResult: ...

    def forget(self, mcp_id: int) -> None: ...

    async def aclose(self) -> None: ...


def _result(status: ScriptStatus, error: str) -> ScriptResult:
    return ScriptResult(
        status=status, exit_code=None, duration_ms=0, stdout="", stderr="",
        stdout_truncated=False, stderr_truncated=False, killed=0, error=error, actual_sha256=None,
    )


class Monitor:
    def __init__(
        self,
        *,
        mcps: McpStore,
        scripts: ScriptStore,
        history: McpHistory,
        settings: SettingsStore,
        runner: ScriptRunnerLike,
        prober: ProberLike,
        log: LogWriter,
        bus: BoardBus,
        clock: Clock,
        tamper: TamperMonitor,
        icon_images: IconImageStore | None = None,
    ) -> None:
        self._mcps = mcps
        self._scripts_store = scripts
        self._history = history
        self._settings = settings
        self._runner = runner
        self._prober = prober
        self._log = log
        self._bus = bus
        self._clock = clock
        self._tamper = tamper
        self._icon_images = icon_images
        self._config: dict[int, Mcp] = {}  # cached Mcp (refreshed on every config write path)
        self._engines: dict[int, McpEngine] = {}
        self._pids: dict[int, int | None] = {}
        self._port_err_at: dict[int, datetime] = {}
        self._pinging: set[int] = set()
        self._checking: set[int] = set()
        self._probes: set[asyncio.Task[None]] = set()
        self._scripts: dict[int, asyncio.Task[None]] = {}
        self._loops: list[asyncio.Task[None]] = []
        # SSE board items shared by every subscriber: mcp id -> (bus version, built at, item).
        self._batch: dict[int, tuple[int, float, dict[str, Any] | None]] = {}
        self._housekeep_n = 0
        self._stopped = False

    # ---- registry ----------------------------------------------------------------

    def engine(self, mcp_id: int) -> McpEngine | None:
        return self._engines.get(mcp_id)

    def add(self, mcp: Mcp) -> None:
        if mcp.id in self._engines:
            raise ValueError(f"MCP {mcp.id} is already monitored")
        if mcp.config_error is not None:
            raise ValueError(f"MCP {mcp.id} has an invalid stored config")
        self._config[mcp.id] = mcp
        self._engines[mcp.id] = McpEngine(mcp.config, self._clock)
        self._bus.mark_dirty(mcp.id)

    def reconfigure(self, mcp: Mcp) -> None:
        engine = self._engines.get(mcp.id)
        if engine is None:
            raise McpNotFoundError(mcp.id)
        old = self._config[mcp.id]
        engine.reconfigure(mcp.config)
        self._config[mcp.id] = mcp
        if old.url != mcp.url:
            self._prober.forget(mcp.id)
        if old.config.maintenance != mcp.config.maintenance:
            self._history.invalidate(mcp.id)  # maintenance time is not counted as uptime
            self._apply(mcp.id, engine.set_maintenance(mcp.config.maintenance))
        self._bus.mark_dirty(mcp.id)

    def republish(self, mcp_id: int) -> None:
        """Send the MCP's board item again (its icon image changed; the config did not)."""
        if mcp_id in self._engines:
            self._bus.mark_dirty(mcp_id)

    def remove(self, mcp_id: int) -> None:
        """Stop monitoring; a no-op for an unknown id. In-flight probe results are dropped."""
        if mcp_id in self._scripts or self._is_running(mcp_id):
            raise ActionInProgressError
        if self._engines.pop(mcp_id, None) is None:
            return
        self._config.pop(mcp_id, None)
        self._pids.pop(mcp_id, None)
        self._port_err_at.pop(mcp_id, None)
        self._batch.pop(mcp_id, None)
        self._history.forget(mcp_id)
        self._prober.forget(mcp_id)
        self._bus.mark_dirty(mcp_id)

    def _is_running(self, mcp_id: int) -> bool:
        engine = self._engines.get(mcp_id)
        return engine is not None and engine.snapshot().running is not None

    # ---- lifecycle ---------------------------------------------------------------

    async def start(self, run_loops: bool = True) -> None:
        """Create engines for MCPs not yet monitored; boot-check the autostart ones among them.

        A row whose stored config fails validation is skipped with a ``system`` event: it stays
        listed by the API (``config_error``) so an admin can fix or delete it.
        """
        for mcp in self._mcps.list():
            if mcp.id in self._engines:
                continue
            if mcp.config_error is not None:
                self._log.emit(
                    "system", event="monitor.mcp_config_invalid", mcp_id=mcp.id, error=mcp.config_error
                )
                continue
            self.add(mcp)
            if mcp.config.autostart_on_boot and not mcp.config.maintenance:
                self._spawn_check(mcp.id, boot=True)
        if run_loops and not self._loops:
            self._loops = [
                asyncio.create_task(self._loop("ping_round", "ping_interval_sec"), name="monitor-ping"),
                asyncio.create_task(
                    self._loop("issue_round", "issue_check_interval_sec"), name="monitor-issue"
                ),
                asyncio.create_task(
                    self._loop("confirm_round", "confirm_interval_sec"), name="monitor-confirm"
                ),
                asyncio.create_task(self._housekeep_loop(), name="monitor-housekeep"),
            ]
        self._log.emit("system", event="monitor.start", mcps=len(self._engines), loops=bool(self._loops))

    async def stop(self, grace_sec: float = DEFAULT_GRACE_SEC, *, kill_abandoned: bool = False) -> None:
        """Cancel loops and probes; give running scripts ``grace_sec``. Scripts still running then are
        abandoned (``abandoned``); with ``kill_abandoned`` (service stop, W21) their process trees are
        killed first (``killed`` processes) and their runs get a moment to record the result."""
        if self._stopped:
            return
        self._stopped = True
        loops, self._loops = self._loops, []
        probes = list(self._probes)
        for task in (*loops, *probes):
            task.cancel()
        await asyncio.gather(*loops, *probes, return_exceptions=True)
        scripts = list(self._scripts.values())
        abandoned = killed = 0
        kill_error: str | None = None
        if scripts:
            _done, pending = await asyncio.wait(scripts, timeout=grace_sec)
            abandoned = len(pending)
            if pending and kill_abandoned:
                try:
                    killed = await self._runner.kill_all()
                except Exception as exc:
                    kill_error = repr(exc)
                _done, pending = await asyncio.wait(pending, timeout=PIPE_DRAIN_SEC + 1)
            for task in pending:
                task.cancel()  # the runner stops waiting; an unkilled script process keeps running
            await asyncio.gather(*pending, return_exceptions=True)
        try:
            self._history.flush()
        except Exception as exc:
            self._log.emit("system", event="monitor.flush_failed", error=repr(exc))
        try:
            await self._prober.aclose()
        except Exception as exc:
            self._log.emit("system", event="monitor.prober_close_failed", error=repr(exc))
        try:
            await self._runner.aclose()
        except Exception as exc:
            self._log.emit("system", event="monitor.runner_close_failed", error=repr(exc))
        extra: dict[str, Any] = {"kill_error": kill_error} if kill_error is not None else {}
        self._log.emit("system", event="monitor.stop", abandoned=abandoned, killed=killed, **extra)

    async def wait_idle(self) -> None:
        """Wait for every probe and script task, including ones spawned meanwhile (tests)."""
        while True:
            tasks = [t for t in (*self._probes, *self._scripts.values()) if not t.done()]
            if not tasks:
                return
            await asyncio.gather(*tasks, return_exceptions=True)

    # ---- loops -------------------------------------------------------------------

    async def _loop(self, round_name: str, interval_key: str) -> None:
        while True:
            try:
                await getattr(self, round_name)()
            except Exception as exc:
                self._log.emit("system", event="monitor.round_failed", loop=round_name, error=repr(exc))
            try:
                interval = float(getattr(self._settings.get(), interval_key))  # re-read every round
            except Exception as exc:
                self._log.emit("system", event="monitor.settings_failed", loop=round_name, error=repr(exc))
                interval = float(getattr(Settings(), interval_key))  # the default
            await asyncio.sleep(interval)

    async def _housekeep_loop(self) -> None:
        while True:
            await asyncio.sleep(HOUSEKEEP_INTERVAL_SEC)
            self._housekeep()

    def _housekeep(self) -> None:
        self._housekeep_n += 1
        try:
            self._history.flush()
            if self._housekeep_n % PURGE_EVERY == 0:
                self._history.purge()
        except Exception as exc:
            self._log.emit("system", event="monitor.housekeep_failed", error=repr(exc))

    # ---- rounds ------------------------------------------------------------------

    async def ping_round(self) -> None:
        for mcp_id in list(self._engines):
            if mcp_id not in self._pinging:
                self._pinging.add(mcp_id)
                self._spawn_probe(self._ping(mcp_id), functools.partial(self._pinging.discard, mcp_id))

    async def issue_round(self) -> None:
        for mcp_id, engine in list(self._engines.items()):
            if engine.needs_issue_check():
                self._spawn_check(mcp_id)

    async def confirm_round(self) -> None:
        for mcp_id, engine in list(self._engines.items()):
            self._apply(mcp_id, engine.tick())
        for mcp_id, engine in list(self._engines.items()):
            if engine.needs_confirm():
                self._spawn_check(mcp_id)

    def _spawn_check(self, mcp_id: int, boot: bool = False) -> None:
        if mcp_id in self._checking:
            return
        self._checking.add(mcp_id)
        self._spawn_probe(self._check(mcp_id, boot), lambda: self._checking.discard(mcp_id))

    def _spawn_probe(self, coro: Awaitable[None], done: Callable[[], None]) -> None:
        task = asyncio.ensure_future(coro)
        self._probes.add(task)

        def _finished(t: asyncio.Task[None]) -> None:
            self._probes.discard(t)
            done()

        task.add_done_callback(_finished)

    def _record(self, mcp_id: int, engine: McpEngine, at: datetime, ok: bool, latency: float | None) -> None:
        counted = engine.state is not McpState.MAINTENANCE  # maintenance time is not uptime
        self._history.record(mcp_id, at, ok, latency, counted=counted)

    async def _ping(self, mcp_id: int) -> None:
        engine, mcp = self._engines.get(mcp_id), self._config.get(mcp_id)
        if engine is None or mcp is None:
            return
        try:
            result = await self._prober.probe(mcp)
        except Exception as exc:
            self._log.emit("system", event="monitor.probe_failed", mcp_id=mcp_id, error=repr(exc))
            return
        if self._engines.get(mcp_id) is not engine:
            return  # removed (or re-added) meanwhile
        self._record(mcp_id, engine, self._clock.now(), result.ok, result.latency_ms)
        self._bus.mark_dirty(mcp_id)

    async def _check(self, mcp_id: int, boot: bool = False) -> None:
        engine, mcp = self._engines.get(mcp_id), self._config.get(mcp_id)
        if engine is None or mcp is None:
            return
        try:
            result = await self._prober.check(mcp)
        except Exception as exc:
            self._log.emit("system", event="monitor.check_failed", mcp_id=mcp_id, error=repr(exc))
            return
        if self._engines.get(mcp_id) is not engine:
            return
        self._record(mcp_id, engine, result.at, result.issue is None, result.latency_ms)
        self._pids[mcp_id] = result.pid
        if result.error and "port_lookup:" in result.error:
            self._report_port_lookup(mcp_id, result.error)
        self._apply(mcp_id, engine.boot(result) if boot else engine.on_check(result))
        self._bus.mark_dirty(mcp_id)

    def _report_port_lookup(self, mcp_id: int, error: str) -> None:
        now = self._clock.now()
        last = self._port_err_at.get(mcp_id)
        if last is None or now - last >= PORT_LOOKUP_LOG_EVERY:
            self._port_err_at[mcp_id] = now
            self._log.emit("system", event="monitor.port_lookup_failed", mcp_id=mcp_id, error=error)

    # ---- effects -----------------------------------------------------------------

    def _apply(
        self, mcp_id: int, effects: list[Effect], actor: User | None = None, run_id: str | None = None
    ) -> None:
        mcp = self._config.get(mcp_id)
        name = mcp.config.name if mcp else None
        for effect in effects:
            if isinstance(effect, Transition):
                issue = effect.issue.value if effect.issue else None
                self._history.record_transition(
                    mcp_id,
                    TransitionRecord(self._clock.now(), effect.from_state, effect.to_state, effect.issue),
                )
                # "from" is a keyword; typed Any so mypy accepts it next to emit's `at=` parameter
                from_field: dict[str, Any] = {"from": effect.from_state.value}
                self._log.emit(
                    "mcp.health", mcp_id=mcp_id, name=name, **from_field,
                    to=effect.to_state.value, issue=issue,
                )
                self._bus.mark_dirty(mcp_id)
            elif isinstance(effect, Alert):
                self._log.emit("mcp.health", mcp_id=mcp_id, name=name, alert=True, issue=effect.issue.value)
            elif isinstance(effect, RunScript):
                tracked = self._scripts.get(mcp_id)
                if tracked is not None and not tracked.done():
                    # Defensive (the engine is single-flight): never start a second script for an
                    # MCP or lose track of the running one. Settle the refused run so the engine
                    # cannot wait for it forever.
                    self._log.emit(
                        "system", event="monitor.action_refused", mcp_id=mcp_id, kind=effect.kind,
                        trigger=effect.trigger, reason="action_in_progress",
                    )
                    engine = self._engines.get(mcp_id)
                    if engine is not None:
                        self._apply(mcp_id, engine.on_action_done(effect, "error"))
                    continue
                rid = run_id or uuid.uuid4().hex
                task = asyncio.ensure_future(self._execute(mcp_id, effect, actor, rid))
                self._scripts[mcp_id] = task
                task.add_done_callback(functools.partial(self._script_done, mcp_id))

    def _script_done(self, mcp_id: int, task: asyncio.Task[None]) -> None:
        if self._scripts.get(mcp_id) is task:
            del self._scripts[mcp_id]

    # ---- manual actions ----------------------------------------------------------

    def manual_action(self, mcp_id: int, kind: ActionKind, actor: User) -> str:
        """Run a script on request; returns the run id. stop enters maintenance, start/restart leave it.

        Order (ruling F5): reject before any write, persist the maintenance flag, then update the
        engine and the cached config.
        """
        engine = self._engines.get(mcp_id)
        if engine is None:
            raise McpNotFoundError(mcp_id)
        if mcp_id in self._scripts or engine.snapshot().running is not None:
            raise ActionInProgressError
        mcp = self._mcps.set_maintenance(mcp_id, kind == "stop")
        if mcp.config.maintenance != self._config[mcp_id].config.maintenance:
            self._history.invalidate(mcp_id)
        engine.reconfigure(mcp.config)
        self._config[mcp_id] = mcp
        run_id = uuid.uuid4().hex
        self._apply(mcp_id, engine.manual(kind), actor=actor, run_id=run_id)
        self._bus.mark_dirty(mcp_id)
        return run_id

    # ---- script execution --------------------------------------------------------

    async def _execute(self, mcp_id: int, run: RunScript, actor: User | None, run_id: str) -> None:
        engine = self._engines.get(mcp_id)
        status: ScriptStatus = "error"
        kind: ActionKind = run.kind
        try:
            if run.kind == "restart" and self._scripts_store.get(mcp_id, "restart") is None:
                await self._run_step(mcp_id, run, "stop", actor, run_id)  # result ignored
                kind = "start"
                status = await self._run_step(mcp_id, run, "start", actor, run_id)
            else:
                status = await self._run_step(mcp_id, run, run.kind, actor, run_id)
        except Exception as exc:
            status = "error"
            self._log.emit(
                "system", event="monitor.action_failed", mcp_id=mcp_id, run_id=run_id, kind=kind,
                error=repr(exc),
            )
            with contextlib.suppress(Exception):
                self._record_step(mcp_id, run, kind, actor, run_id, self._clock.now(), _result("error", "internal"))
        if engine is not None and self._engines.get(mcp_id) is engine:
            self._apply(mcp_id, engine.on_action_done(run, status))
            self._bus.mark_dirty(mcp_id)

    async def _run_step(
        self, mcp_id: int, run: RunScript, kind: ActionKind, actor: User | None, run_id: str
    ) -> ScriptStatus:
        mcp = self._config[mcp_id]
        config = mcp.config
        info = self._scripts_store.get(mcp_id, kind)
        at = self._clock.now()
        if info is None:
            result = _result("error", "missing")
        else:
            pid = self._pids.get(mcp_id)
            # Script env contract (cmd expands %VAR% before it parses a line or a parenthesized
            # block, so these values must carry no cmd syntax):
            # - MCP_NAME: only Unicode letters/digits, space, "." "_" "-" (McpConfig allowlist;
            #   1-64 chars, no leading/trailing space).
            # - MCP_HOST: a lowercase hostname, IPv4 or canonical IPv6 literal (may contain ":").
            # - MCP_ID, MCP_PORT, MCP_PID: decimal digits (MCP_PID may be empty).
            # - MCP_REASON, MCP_TRIGGER: fixed identifiers (issue code or "manual"; auto/manual/boot).
            # - MCP_ACTOR: "system", a user's email made only of [A-Za-z0-9._%+-@], else "user-<id>"
            #   (safe_actor, W37: users/store.py permits "&" in emails). "%" in a value is not
            #   expanded again. The mcp.action log keeps the real email.
            env = {
                "MCP_ID": str(mcp_id),
                "MCP_NAME": config.name,
                "MCP_HOST": config.host,
                "MCP_PORT": str(config.port),
                "MCP_PID": "" if pid is None else str(pid),
                "MCP_REASON": run.reason,
                "MCP_TRIGGER": run.trigger,
                "MCP_ACTOR": safe_actor(actor),
            }
            resolved: ScriptInfo | None = info

            def resolve() -> ScriptTarget | None:
                # Spec 5.8: compare with the DB right before execution. The run may wait for the
                # MCP lock and a global slot (minutes when slots hang); an owner edit meanwhile is
                # the new expected script, not tampering.
                nonlocal resolved
                resolved = self._scripts_store.get(mcp_id, kind)
                return None if resolved is None else (resolved.path, resolved.sha256)

            result = await self._runner.run(
                info.path,
                expected_sha256=info.sha256,
                timeout_sec=config.script_timeout_sec,
                env=env,
                lock_key=mcp_id,
                resolve=resolve,
            )
            if result.error == "hash_mismatch":
                checked = resolved or info
                self._tamper.report(
                    "script_hash_mismatch", mcp_id=mcp_id, kind=kind, path=str(checked.path),
                    expected_sha256=checked.sha256, actual_sha256=result.actual_sha256,
                )
            elif result.error == "internal":
                self._log.emit(
                    "system", event="monitor.runner_internal", mcp_id=mcp_id, run_id=run_id, kind=kind,
                    error=result.stderr or "internal",
                )
            elif result.error == "kill_failed":
                self._log.emit("system", event="monitor.kill_failed", mcp_id=mcp_id, run_id=run_id, kind=kind)
        self._record_step(mcp_id, run, kind, actor, run_id, at, result)
        return result.status

    def _record_step(
        self, mcp_id: int, run: RunScript, kind: ActionKind, actor: User | None, run_id: str,
        at: datetime, result: ScriptResult,
    ) -> None:
        mcp = self._config.get(mcp_id)
        self._history.record_action(
            ActionRecord(
                run_id=run_id, mcp_id=mcp_id, at=at, requested=run.kind, kind=kind,
                trigger=run.trigger, reason=run.reason,
                actor_id=actor.id if actor is not None else None, result=result,
            )
        )
        self._log.emit(
            "mcp.action",
            mcp_id=mcp_id,
            name=mcp.config.name if mcp else None,
            run_id=run_id,
            kind=kind,
            requested=run.kind,
            trigger=run.trigger,
            reason=run.reason,
            actor=actor.email if actor is not None else "system",
            status=result.status,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            killed=result.killed,
            error=result.error,
            stdout=result.stdout[:LOG_OUTPUT_CHARS],
            stderr=result.stderr[:LOG_OUTPUT_CHARS],
        )
        # Output stays out of the stream; action events go to signed-in subscribers only (ruling F7).
        self._bus.publish(
            "action",
            {
                "run_id": run_id, "mcp_id": mcp_id, "kind": kind, "requested": run.kind,
                "trigger": run.trigger, "status": result.status, "exit_code": result.exit_code, "duration_ms": result.duration_ms,
            },
            public=False,
        )

    # ---- board -------------------------------------------------------------------

    def board_item(self, mcp_id: int) -> dict[str, Any] | None:
        engine, mcp = self._engines.get(mcp_id), self._config.get(mcp_id)
        if engine is None or mcp is None:
            return None
        snap = engine.snapshot()
        spark = self._history.sparkline(mcp_id)
        last = self._history.last_check_at(mcp_id)
        due = snap.action_due_at
        in_sec = None
        if due is not None:
            in_sec = round(max(0.0, (due - self._clock.now()).total_seconds()), 1)
        return {
            "id": mcp_id,
            "name": mcp.config.name,
            "icon": mcp.config.icon,
            "icon_image": self._icon_images.url(mcp_id) if self._icon_images is not None else None,
            "state": snap.state.value,
            "issue": snap.issue.value if snap.issue else None,
            "latency_ms": spark[-1] if spark else None,
            "sparkline": spark,
            "uptime_24h": self._history.uptime(mcp_id, 24),
            "last_check_at": to_kst_iso(last) if last else None,
            "action_due_at": to_kst_iso(due) if due else None,
            "action_in_sec": in_sec,
            "action_delay_sec": mcp.config.action_delay_sec if due is not None else None,
            "maintenance": mcp.config.maintenance,
            "running": snap.running.kind if snap.running else None,
        }

    def batch_item(self, mcp_id: int) -> dict[str, Any] | None:
        """``board_item`` shared by every SSE subscriber (I3): built once per change, not per stream.

        Rebuilt when the MCP is marked dirty again (a newer bus version) or after
        BATCH_ITEM_TTL_SEC, so countdowns and uptime are never older than one coalesce period.
        """
        version = self._bus.version(mcp_id)
        now = time.monotonic()
        cached = self._batch.get(mcp_id)
        if cached is not None and cached[0] == version and now - cached[1] < BATCH_ITEM_TTL_SEC:
            return cached[2]
        item = self.board_item(mcp_id)
        if item is None:
            self._batch.pop(mcp_id, None)
        else:
            self._batch[mcp_id] = (version, now, item)
        return item

    def board_snapshot(self) -> dict[str, Any]:
        """The whole board as the API serves it (GET /api/board and the first SSE event)."""
        return {"now": to_kst_iso(self._clock.now()), "mcps": self.board()}

    def board(self) -> list[dict[str, Any]]:
        order = sorted(self._config.values(), key=lambda m: (m.config.name.casefold(), m.id))
        return [item for m in order if (item := self.board_item(m.id)) is not None]
