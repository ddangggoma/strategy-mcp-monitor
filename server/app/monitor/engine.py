"""Pure MCP monitor state machine.

No I/O, no timers: the caller feeds check results / ticks / script completions and
executes the returned effects.  Time comes only from the injected ``Clock`` and from
``CheckResult.at``.  Effects are always ordered Transition -> RunScript -> Alert, and a
Transition is only emitted when the state actually changes.  Events that arrive in a
state where they have no meaning are ignored (never raise).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.clock import Clock
from app.monitor.models import (
    ALERT_ONLY_ISSUES,
    ActionKind,
    CheckResult,
    Issue,
    McpConfig,
    McpState,
    ScriptStatus,
    Trigger,
)

# Longest possible McpConfig.window_sec; older auto-action stamps can never count again.
_MAX_WINDOW = timedelta(seconds=86400)


@dataclass(frozen=True)
class Transition:
    from_state: McpState
    to_state: McpState
    issue: Issue | None


@dataclass(frozen=True)
class RunScript:
    kind: ActionKind
    trigger: Trigger
    reason: str  # issue value, or "manual"


@dataclass(frozen=True)
class Alert:
    issue: Issue


Effect = Transition | RunScript | Alert


class ActionInProgressError(Exception):
    """A script is already running for this MCP."""


@dataclass(frozen=True)
class EngineSnapshot:
    state: McpState
    issue: Issue | None
    state_since: datetime
    action_due_at: datetime | None
    auto_actions_in_window: int
    alerted: bool
    running: RunScript | None


class McpEngine:
    def __init__(self, config: McpConfig, clock: Clock) -> None:
        self._config = config
        self._clock = clock
        self._state = McpState.MAINTENANCE if config.maintenance else McpState.HEALTHY
        self._state_since = clock.now()
        self._issue: Issue | None = None
        self._suspect_since: datetime | None = None
        self._grace_until: datetime | None = None
        self._alerted = False
        self._running: RunScript | None = None
        self._auto_stamps: list[datetime] = []

    # -- read side ---------------------------------------------------------------

    @property
    def state(self) -> McpState:
        return self._state

    @property
    def config(self) -> McpConfig:
        return self._config

    def needs_issue_check(self) -> bool:
        return self._state is McpState.HEALTHY

    def needs_confirm(self) -> bool:
        return self._state in (McpState.SUSPECT, McpState.RECOVERING)

    def snapshot(self) -> EngineSnapshot:
        return EngineSnapshot(
            state=self._state,
            issue=self._issue,
            state_since=self._state_since,
            action_due_at=self._action_due_at(),
            auto_actions_in_window=self._window_count(self._clock.now()),
            alerted=self._alerted,
            running=self._running,
        )

    # -- inputs ------------------------------------------------------------------

    def on_check(self, result: CheckResult) -> list[Effect]:
        state = self._state
        if state is McpState.HEALTHY:
            if result.issue is None:
                return []
            return self._enter_suspect(result)
        if state is McpState.SUSPECT:
            return self._check_in_suspect(result)
        if state is McpState.RECOVERING:
            if result.issue is None:
                return self._move(McpState.HEALTHY, None)
            return self._enter_suspect(result)
        return []  # ACTION / FAILED / MAINTENANCE: checks are ignored

    def boot(self, result: CheckResult) -> list[Effect]:
        """First check after service start: may autostart a down MCP (not budgeted)."""
        if (
            self._state is McpState.HEALTHY
            and self._running is None
            and self._config.autostart_on_boot
            and result.issue is Issue.PROCESS_DOWN
        ):
            run = RunScript("start", "boot", Issue.PROCESS_DOWN.value)
            self._issue = Issue.PROCESS_DOWN
            effects: list[Effect] = self._move(McpState.ACTION, Issue.PROCESS_DOWN)
            self._grace_until = None
            self._running = run
            effects.append(run)
            return effects
        return self.on_check(result)

    def tick(self) -> list[Effect]:
        if (
            self._state is McpState.ACTION
            and self._running is None
            and self._grace_until is not None
            and self._clock.now() >= self._grace_until
        ):
            return self._move(McpState.RECOVERING, self._issue)
        return []

    def on_action_done(self, run: RunScript, status: ScriptStatus) -> list[Effect]:
        if self._running is None or run != self._running:
            return []  # stale / unknown completion: nothing to settle
        self._running = None
        if self._state is not McpState.ACTION:
            return []  # state moved on (maintenance, FAILED stop, ...): result is moot
        now = self._clock.now()
        if status == "ok":
            grace = self._config.startup_grace_sec
            if grace > 0:
                self._grace_until = now + timedelta(seconds=grace)
                return []
            return self._move(McpState.RECOVERING, self._issue)
        if run.trigger == "manual":
            return self._move(McpState.RECOVERING, self._issue)
        # failed auto/boot action: wait a full action_delay again (backoff)
        self._suspect_since = now
        return self._move(McpState.SUSPECT, self._issue)

    def manual(self, kind: ActionKind) -> list[Effect]:
        if self._running is not None:
            raise ActionInProgressError
        run = RunScript(kind, "manual", "manual")
        target = McpState.MAINTENANCE if kind == "stop" else McpState.ACTION
        self._issue = None
        self._grace_until = None  # a manual action during a grace period replaces it
        effects = self._move(target, None)
        self._running = run
        effects.append(run)
        return effects

    def set_maintenance(self, on: bool) -> list[Effect]:
        if on:
            return self._move(McpState.MAINTENANCE, None)
        if self._state is McpState.MAINTENANCE:
            return self._move(McpState.HEALTHY, None)
        return []

    def reconfigure(self, config: McpConfig) -> None:
        self._config = config

    # -- internals ---------------------------------------------------------------

    def _move(self, to_state: McpState, issue: Issue | None) -> list[Effect]:
        """Change state (clearing per-state bookkeeping); no effect if state is unchanged."""
        from_state = self._state
        if to_state in (McpState.HEALTHY, McpState.MAINTENANCE):
            self._issue = None
            self._suspect_since = None
            self._grace_until = None
            self._alerted = False
        if to_state is not McpState.ACTION:
            self._grace_until = None
        if from_state is to_state:
            return []
        self._state = to_state
        self._state_since = self._clock.now()
        return [Transition(from_state, to_state, issue)]

    def _enter_suspect(self, result: CheckResult) -> list[Effect]:
        self._issue = result.issue
        self._suspect_since = result.at
        self._alerted = False
        return self._move(McpState.SUSPECT, result.issue)

    def _check_in_suspect(self, result: CheckResult) -> list[Effect]:
        if result.issue is None:
            return self._move(McpState.HEALTHY, None)
        issue = result.issue
        self._issue = issue
        since = self._suspect_since if self._suspect_since is not None else result.at
        if result.at - since < timedelta(seconds=self._config.action_delay_sec):
            return []
        if issue in ALERT_ONLY_ISSUES or not self._config.auto_recovery:
            if self._alerted:
                return []
            self._alerted = True
            return [Alert(issue)]
        now = self._clock.now()
        if self._window_count(now) < self._config.max_auto_actions:
            self._auto_stamps.append(now)
            self._prune(now)
            run = RunScript("start" if issue is Issue.PROCESS_DOWN else "restart", "auto", issue.value)
            effects = self._move(McpState.ACTION, issue)
            self._running = run
            effects.append(run)
            return effects
        run = RunScript("stop", "auto", issue.value)
        effects = self._move(McpState.FAILED, issue)
        self._running = run
        effects.append(run)
        effects.append(Alert(issue))
        return effects

    def _window_count(self, now: datetime) -> int:
        window = timedelta(seconds=self._config.window_sec)
        return sum(1 for stamp in self._auto_stamps if now - stamp < window)

    def _prune(self, now: datetime) -> None:
        self._auto_stamps = [s for s in self._auto_stamps if now - s < _MAX_WINDOW]

    def _action_due_at(self) -> datetime | None:
        if (
            self._state is McpState.SUSPECT
            and self._suspect_since is not None
            and self._issue is not None
            and self._issue not in ALERT_ONLY_ISSUES
            and self._config.auto_recovery
            and not self._alerted
        ):
            return self._suspect_since + timedelta(seconds=self._config.action_delay_sec)
        return None
