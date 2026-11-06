"""Starts and stops the Windows collectors and keeps their health (``GET /api/sessions/collectors``).

A ``Component`` owns a collector thread: ``start(bridge)`` runs on the loop thread, registers its
bridge handler(s) and starts the thread; ``stop()`` may block (it is run with ``asyncio.to_thread``).
Plain asyncio jobs are added with ``add_task``. One component failing to start is reported and the
others still start.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.clock import Clock
from app.collect.bridge import CollectorBridge
from app.logstore.writer import LogSink
from app.sessions.collector import SessionCollector, WtsFailure
from app.sessions.rdns import ReverseDns
from app.sessions.tracker import Change, Opened, SessionTracker
from app.win.wts import WtsSnapshot, WtsSource


class Component(Protocol):
    name: str

    def start(self, bridge: CollectorBridge) -> None:
        """Called on the loop thread; registers bridge handlers and starts the collector thread."""
        ...

    def stop(self) -> None:
        """May block; called through ``asyncio.to_thread``."""
        ...


@dataclass
class CollectorStatus:
    name: str
    ok: bool
    error: str | None
    since: datetime


class Collectors:
    def __init__(self, log: LogSink, clock: Clock) -> None:
        self._log = log
        self._clock = clock
        self._components: list[Component] = []
        self._task_fns: list[tuple[str, Callable[[], Awaitable[None]]]] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._status: dict[str, CollectorStatus] = {}
        self._modes: dict[str, str] = {}
        self._started = False
        self.bridge: CollectorBridge | None = None

    def add(self, component: Component) -> None:
        self._components.append(component)

    def add_task(self, name: str, fn: Callable[[], Awaitable[None]]) -> None:
        """``fn()`` runs as a task from ``start()`` until ``stop()`` cancels it."""
        self._task_fns.append((name, fn))

    async def start(self) -> None:
        if self._started:
            raise RuntimeError("collectors already started")
        self._started = True
        self.bridge = CollectorBridge(asyncio.get_running_loop(), self._log)
        for component in self._components:
            try:
                component.start(self.bridge)
            except Exception as exc:  # one collector that cannot start must not stop the others
                self.report(component.name, False, repr(exc))
        for name, fn in self._task_fns:
            self._tasks.append(asyncio.create_task(_run(fn), name=name))

    async def stop(self) -> None:
        """Cancel the tasks, then stop each component (in reverse order) off the loop."""
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if not self._started:
            return
        self._started = False
        for component in reversed(self._components):
            try:
                await asyncio.to_thread(component.stop)
            except Exception as exc:
                self.report(component.name, False, f"stop failed: {exc!r}")

    def report(self, name: str, ok: bool, error: str | None = None) -> None:
        """Record a collector's health; ``since`` moves and a ``collector.status`` line is written
        only when ``(ok, error)`` changes."""
        current = self._status.get(name)
        if current is not None and (current.ok, current.error) == (ok, error):
            return
        self._status[name] = CollectorStatus(name, ok, error, self._clock.now())
        self._log.emit("system", event="collector.status", source=name, ok=ok, error=error)

    def report_mode(self, source: str, mode: str) -> None:
        """Record how a collector reads (e.g. WMI ``trace`` or ``poll``); a ``collector.mode`` line
        is written only when the mode of that source changes."""
        if self._modes.get(source) == mode:
            return
        self._modes[source] = mode
        self._log.emit("system", event="collector.mode", source=source, mode=mode)

    def handler_failed(self, source: str, exc: BaseException) -> None:
        """Log a loop-side handler error the way the bridge does (``collector.handler_failed``)."""
        self._log.emit("system", event="collector.handler_failed", source=source, error=repr(exc))

    def status(self) -> list[CollectorStatus]:
        return [self._status[name] for name in sorted(self._status)]


async def _run(fn: Callable[[], Awaitable[None]]) -> None:
    await fn()


class SessionsComponent:
    """WTS polling → ``SessionTracker`` on the loop, plus reverse DNS for each new connection."""

    name = "wts"

    def __init__(
        self,
        source: WtsSource,
        tracker: SessionTracker,
        collectors: Collectors,
        rdns: ReverseDns,
        clock: Clock,
        *,
        interval_sec: float,
    ) -> None:
        self._source = source
        self._tracker = tracker
        self._collectors = collectors
        self._rdns = rdns
        self._clock = clock
        self._interval_sec = interval_sec
        self._collector: SessionCollector | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lookups: set[asyncio.Task[None]] = set()
        self._stopped = False

    @property
    def alive(self) -> bool:
        return self._collector is not None and self._collector.alive

    def start(self, bridge: CollectorBridge) -> None:
        self._loop = asyncio.get_running_loop()
        self._tracker.start()
        post = bridge.register(self.name, self._handle)
        self._tracker.add_listener(self._on_change)
        self._collector = SessionCollector(
            self._source, post, self._clock, interval_sec=self._interval_sec
        )
        self._collector.start()

    def nudge(self) -> None:
        if self._collector is not None:
            self._collector.nudge()

    def stop(self) -> None:
        self._stopped = True
        if self._collector is not None:
            self._collector.stop()
        loop = self._loop
        if loop is not None:
            for task in list(self._lookups):
                try:
                    loop.call_soon_threadsafe(task.cancel)
                except RuntimeError:  # loop already closed
                    pass

    def _handle(self, items: list[Any]) -> None:
        """Bridge handler (loop thread): apply snapshots in order, report failures."""
        for item in items:
            if isinstance(item, WtsSnapshot):
                self._tracker.apply(item)
                self._collectors.report(self.name, True)
            elif isinstance(item, WtsFailure):
                self._tracker.failed(item.error)
                self._collectors.report(self.name, False, item.error)

    def _on_change(self, change: Change) -> None:
        if not isinstance(change, Opened) or self._stopped:
            return
        ip = change.connection.client_ip
        if ip is None:
            return
        task = asyncio.get_running_loop().create_task(self._resolve(change.connection.id, ip))
        self._lookups.add(task)
        task.add_done_callback(self._lookups.discard)

    async def _resolve(self, connection_id: int, ip: str) -> None:
        try:
            name = await self._rdns.resolve(ip)
            if name is not None and not self._stopped:
                self._tracker.set_reverse_dns(connection_id, name)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # an odd resolver error must not become an unretrieved task error
            self._collectors.handler_failed(f"{self.name}:rdns", exc)
