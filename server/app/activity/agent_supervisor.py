"""Keeps one session agent running in every connected RDP session (spec §5.5, §13).

On ``Opened`` the supervisor launches the session's agent with a fresh hub token (or, if the agent
is alive, asks the hub to show the pending notice: the hub shows a display once per agent, F09).
``tick`` (every ``tick_sec`` from ``run``) watches each agent:

* no hello within ``hello_timeout_sec`` of the launch, or no request within
  ``heartbeat_timeout_sec`` after it → ``tamper agent_unresponsive`` and we kill it;
* an exit is classified ``exit_grace_sec`` after it was first seen: the session gone means logoff
  (``session agent_stopped``, not a bypass); otherwise ``tamper agent_exited`` unless we killed it,
  the open notice is logged unconfirmed, and the agent is relaunched after a backoff (reset by a
  healthy run); ``storm_count`` exits within ``storm_window_sec`` → one ``agent_restart_storm``.

Launch failures are logged (``system agent.launch_failed``) and retried on the backoff, except a
deterministic one (``session_mismatch``: a local launcher and another session), which waits for
the session's next ``Opened`` (ruling F22).

``pid`` in the log lines is the launcher's process; ``agent_pid`` is the pid the agent said hello
from (the hub's TCP-peer-verified pid; F08). ``stop`` asks every agent to exit, waits
``stop_grace_sec`` and kills the rest (ruling F07: ``Collectors.stop`` awaits it first).

Loop thread only.
"""

from __future__ import annotations

import asyncio
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final, Literal

from app.activity.agent_hub import AgentHub
from app.activity.tamper import TamperMonitor
from app.clock import Clock
from app.logstore.writer import LogSink
from app.sessions.tracker import Change, Closed, Opened, SessionTracker
from app.win.launch import AgentLauncher, AgentProcess, LaunchError, LaunchSpec

_REPO = Path(__file__).resolve().parents[3]
_PERMANENT_ERRORS: Final = frozenset({"session_mismatch", "disabled"})
_STOP_POLL_SEC: Final = 0.05


def _agent_python() -> str:
    """The base interpreter, not a venv's ``python.exe`` redirector: the agent is stdlib-only
    (``PYTHONPATH`` = the agent folder), and without the redirector the launched pid is the agent's
    own pid (F08)."""
    return getattr(sys, "_base_executable", None) or sys.executable


@dataclass(frozen=True)
class AgentOptions:
    dialog: Literal["edge", "print"] = "edge"
    agent_dir: Path = _REPO / "agent"
    python: str = field(default_factory=_agent_python)
    url_dir: Path | None = None
    """``--dialog print``: the agent writes the notice URL to ``<url_dir>/agent-<session>.url``."""
    hello_timeout_sec: float = 30
    heartbeat_timeout_sec: float = 20
    exit_grace_sec: float = 3
    backoff: tuple[float, ...] = (1, 2, 4, 8, 16, 30)
    healthy_reset_sec: float = 60
    storm_count: int = 5
    storm_window_sec: float = 600
    tick_sec: float = 1.0
    stop_grace_sec: float = 2.0


@dataclass(eq=False)
class _Agent:
    """A session's agent: the running process, or the wait before the next launch."""

    session_id: int
    user: str
    proc: AgentProcess | None = None
    launched_at: datetime | None = None
    launches: int = 0
    killed: bool = False
    """We killed it (unresponsive, logoff): its exit is not ``agent_exited``."""
    exited_at: datetime | None = None
    exit_code: int | None = None
    agent_pid: int | None = None
    hello_at: datetime | None = None
    relaunch_at: datetime | None = None
    blocked: bool = False
    """A deterministic launch failure: no retry before the next ``Opened`` (F22)."""
    failures: int = 0
    exits: deque[datetime] = field(default_factory=deque)
    storm_reported_at: datetime | None = None


class AgentSupervisor:
    def __init__(
        self,
        hub: AgentHub,
        launcher: AgentLauncher,
        tracker: SessionTracker,
        tamper: TamperMonitor,
        log: LogSink,
        clock: Clock,
        options: AgentOptions,
    ) -> None:
        if options.dialog == "print" and options.url_dir is None:
            raise ValueError("AgentOptions(dialog='print') needs a url_dir")
        if not options.backoff:
            raise ValueError("AgentOptions.backoff must not be empty")
        self._hub = hub
        self._launcher = launcher
        self._tracker = tracker
        self._tamper = tamper
        self._log = log
        self._clock = clock
        self._options = options
        self._server_url = "http://127.0.0.1:8700"
        self._agents: dict[int, _Agent] = {}
        self._stopping = False

    def configure(self, server_url: str) -> None:
        """The Local channel URL the agents talk to (``serve()`` passes the real port)."""
        self._server_url = server_url.rstrip("/")

    # --- session changes -------------------------------------------------------------------

    def on_session_change(self, change: Change) -> None:
        """Tracker listener (registered after the display listener)."""
        if isinstance(change, Opened):
            self.ensure(change.connection.session_id)
        elif isinstance(change, Closed) and change.reason == "logoff":
            self.forget(change.session_id)

    def ensure(self, session_id: int) -> None:
        """An agent for this (just connected) session: launch one, or show the pending notice."""
        if self._stopping:
            return
        agent = self._agents.get(session_id)
        if agent is None or (agent.proc is None and (agent.relaunch_at is None or agent.blocked)):
            self._launch(session_id)
        elif agent.proc is not None and agent.proc.poll() is None:
            self._hub.show_pending(session_id)

    def forget(self, session_id: int) -> None:
        """The session logged off: end its agent (we kill it), drop its token and state."""
        agent = self._agents.pop(session_id, None)
        if agent is not None and agent.proc is not None:
            self._note_hello(agent)
        self._hub.revoke(session_id)
        if agent is None or agent.proc is None:
            return
        if agent.proc.poll() is None:
            agent.killed = True
            agent.proc.kill()
        self._stopped_by_logoff(agent)

    # --- launching -------------------------------------------------------------------------

    def _launch(self, session_id: int) -> None:
        ctx = self._tracker.context(session_id)
        if ctx is None:
            return
        agent = self._agents.get(session_id)
        if agent is None:
            agent = _Agent(session_id, ctx.account)
            self._agents[session_id] = agent
        agent.user = ctx.account
        agent.relaunch_at = None
        agent.blocked = False
        opts = self._options
        argv = [opts.python, "-m", "mcp_agent", "--server", self._server_url, "--dialog", opts.dialog]
        token = self._hub.mint(session_id, ctx.account)
        try:
            if opts.dialog == "print":
                assert opts.url_dir is not None  # checked in __init__
                try:
                    opts.url_dir.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    raise LaunchError(repr(exc)) from exc
                argv += ["--url-file", str(opts.url_dir / f"agent-{session_id}.url")]
            env = {"MCPMON_AGENT_TOKEN": token, "PYTHONPATH": str(opts.agent_dir)}
            proc = self._launcher.launch(LaunchSpec(session_id, argv, env, opts.agent_dir))
        except LaunchError as exc:
            self._hub.revoke(session_id)
            error = str(exc)
            self._log.emit(
                "system", event="agent.launch_failed", session_id=session_id,
                launcher=self._launcher.name, error=error,
            )
            if error in _PERMANENT_ERRORS:
                agent.blocked = True
            else:
                self._schedule_relaunch(agent)
            return
        agent.proc = proc
        agent.launched_at = self._clock.now()
        agent.launches += 1
        agent.killed = False
        agent.exited_at = agent.exit_code = agent.agent_pid = agent.hello_at = None
        self._log.emit(
            "system", event="agent.launched", session_id=session_id, pid=proc.pid,
            launcher=self._launcher.name,
        )

    def _schedule_relaunch(self, agent: _Agent) -> None:
        """``backoff[n]`` from now, ``n`` = the failures in a row before this one."""
        backoff = self._options.backoff
        delay = backoff[min(agent.failures, len(backoff) - 1)]
        agent.failures += 1
        agent.relaunch_at = self._clock.now() + timedelta(seconds=delay)

    # --- watching --------------------------------------------------------------------------

    async def run(self) -> None:
        """``tick`` every ``tick_sec`` until ``stop`` (a ``Collectors`` task)."""
        while not self._stopping:
            try:
                self.tick()
            except Exception as exc:  # one bad tick must not end the supervision
                self._log.emit(
                    "system", event="collector.handler_failed", source="agent-supervisor",
                    error=repr(exc),
                )
            await asyncio.sleep(self._options.tick_sec)

    def tick(self) -> None:
        if self._stopping:
            return
        now = self._clock.now()
        for agent in list(self._agents.values()):
            proc = agent.proc
            if proc is None:
                self._tick_waiting(agent, now)
                continue
            code = proc.poll()
            if code is None:
                self._tick_alive(agent, proc, now)
            else:
                self._tick_exited(agent, code, now)

    def _tick_waiting(self, agent: _Agent, now: datetime) -> None:
        if self._tracker.context(agent.session_id) is None:  # gone while we waited
            self._drop(agent)
            return
        if not agent.blocked and agent.relaunch_at is not None and now >= agent.relaunch_at:
            self._launch(agent.session_id)

    def _tick_alive(self, agent: _Agent, proc: AgentProcess, now: datetime) -> None:
        if agent.killed:
            return
        self._note_hello(agent)
        slot = self._hub.slot(agent.session_id)
        stage: str | None = None
        if agent.hello_at is None:
            assert agent.launched_at is not None
            if (now - agent.launched_at).total_seconds() > self._options.hello_timeout_sec:
                stage = "hello"
        elif slot is not None and slot.last_seen is not None:
            if (now - slot.last_seen).total_seconds() > self._options.heartbeat_timeout_sec:
                stage = "heartbeat"
        if stage is None:
            return
        self._tamper.report(
            "agent_unresponsive", session_id=agent.session_id, user=agent.user, pid=proc.pid,
            agent_pid=agent.agent_pid, stage=stage,
        )
        agent.killed = True
        proc.kill()

    def _tick_exited(self, agent: _Agent, code: int, now: datetime) -> None:
        if agent.exited_at is None:
            self._note_hello(agent)
            agent.exited_at, agent.exit_code = now, code
            return
        if (now - agent.exited_at).total_seconds() < self._options.exit_grace_sec:
            return
        assert agent.proc is not None
        sid = agent.session_id
        if self._tracker.context(sid) is None:  # the session logged off: not a bypass
            self._stopped_by_logoff(agent)
            self._drop(agent)
            return
        if not agent.killed:
            self._tamper.report(
                "agent_exited", session_id=sid, user=agent.user, pid=agent.proc.pid,
                agent_pid=agent.agent_pid, exit_code=agent.exit_code,
                restarts=agent.launches - 1,
            )
        self._hub.agent_exited(sid)  # its open notice went unconfirmed (it is shown again)
        self._hub.revoke(sid)
        self._count_exit(agent, now)
        if (
            agent.hello_at is not None
            and (agent.exited_at - agent.hello_at).total_seconds() > self._options.healthy_reset_sec
        ):
            agent.failures = 0
        agent.proc = None
        self._schedule_relaunch(agent)

    def _count_exit(self, agent: _Agent, now: datetime) -> None:
        window = timedelta(seconds=self._options.storm_window_sec)
        agent.exits.append(now)
        while agent.exits and now - agent.exits[0] > window:
            agent.exits.popleft()
        if len(agent.exits) < self._options.storm_count:
            return
        if agent.storm_reported_at is not None and now - agent.storm_reported_at <= window:
            return
        agent.storm_reported_at = now
        self._tamper.report(
            "agent_restart_storm", session_id=agent.session_id, user=agent.user,
            exits=len(agent.exits),
        )

    def _note_hello(self, agent: _Agent) -> None:
        """Copy the current launch's hello (pid, time) from its hub slot."""
        slot = self._hub.slot(agent.session_id)
        if slot is not None and slot.hello_at is not None:  # a launch mints its own slot
            agent.agent_pid, agent.hello_at = slot.pid, slot.hello_at

    def _stopped_by_logoff(self, agent: _Agent) -> None:
        assert agent.proc is not None
        self._log.emit(
            "session", event="agent_stopped", session_id=agent.session_id, user=agent.user,
            pid=agent.proc.pid, agent_pid=agent.agent_pid, reason="logoff",
        )

    def _drop(self, agent: _Agent) -> None:
        self._agents.pop(agent.session_id, None)
        self._hub.revoke(agent.session_id)

    # --- shutdown --------------------------------------------------------------------------

    async def stop(self) -> None:
        """Ask every live agent to exit, wait up to ``stop_grace_sec``, kill the rest; supervision
        ends (no relaunch, no tamper report for these exits)."""
        self._stopping = True
        live = [a for a in self._agents.values() if a.proc is not None and a.proc.poll() is None]
        for agent in live:
            self._hub.queue(agent.session_id, {"type": "exit"})
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._options.stop_grace_sec
        while True:
            running = [a for a in live if a.proc is not None and a.proc.poll() is None]
            remaining = deadline - loop.time()
            if not running or remaining <= 0:
                break
            await asyncio.sleep(min(_STOP_POLL_SEC, remaining))
        for agent in running:
            agent.killed = True
            assert agent.proc is not None
            await asyncio.to_thread(agent.proc.kill)
        for session_id in list(self._agents):
            self._hub.revoke(session_id)
        self._agents.clear()
