"""Move coalesced window events and idle transitions from the hook thread to the sender."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from mcp_agent.client import AgentRejected
from mcp_agent.coalesce import RawWinEvent, WindowEventCoalescer
from mcp_agent.idle import IdleTracker

STEP_SEC = 0.25
FLUSH_SEC = 1.0


class _Sender(Protocol):
    def add(self, item: RawWinEvent | dict[str, Any]) -> None: ...

    def flush(self) -> None: ...


class EventPump:
    def __init__(self, coalescer: WindowEventCoalescer, sender: _Sender, idle_tracker: IdleTracker, *,
                 idle_seconds: Callable[[], float], idle_every_sec: float = 5.0) -> None:
        self._coalescer = coalescer
        self._sender = sender
        self._idle = idle_tracker
        self._idle_seconds = idle_seconds
        self._idle_every = idle_every_sec
        self._last_idle_check: float | None = None
        self._lock = threading.Lock()

    def on_raw(self, e: RawWinEvent) -> None:
        """Called on the hook thread: only a lock and a list append."""
        with self._lock:
            self._coalescer.add(e)

    def step(self, mono: float, wall: datetime) -> None:
        with self._lock:
            ready = self._coalescer.drain(mono)
        for e in ready:
            self._sender.add(e)
        if self._last_idle_check is None or mono - self._last_idle_check >= self._idle_every:
            self._last_idle_check = mono
            try:
                idle_sec = self._idle_seconds()
            except OSError:
                return  # e.g. no input info on a disconnected desktop; try again next time
            change = self._idle.update(idle_sec, wall)
            if change is not None:
                self._sender.add(change)

    def run(self, stop: threading.Event) -> None:
        """Step every 0.25 s and flush every second until ``stop`` is set or the token is rejected."""
        next_flush = time.monotonic() + FLUSH_SEC
        while not stop.wait(STEP_SEC):
            mono = time.monotonic()
            try:
                self.step(mono, datetime.now(UTC))
                if mono >= next_flush:
                    next_flush = mono + FLUSH_SEC
                    self._sender.flush()
            except AgentRejected:
                return  # the runner sees the rejection too and exits
            except Exception as e:  # noqa: BLE001 - the pump must outlive one bad step
                print(f"mcp_agent: event pump: {e!r}", file=sys.stderr)
