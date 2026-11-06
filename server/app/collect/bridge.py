"""Hands items from collector threads to handlers on the asyncio loop, in batches.

Collector threads never touch ``LogWriter``/``Database``/``BoardBus`` directly: they call the
``post`` function returned by :meth:`CollectorBridge.register`, and the handler runs later on the
loop thread with everything posted since the last drain. Each source keeps at most
``max_pending`` items; on overflow the oldest are dropped and the count is logged once per drain.
"""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from collections.abc import Callable
from typing import Any

from app.logstore.writer import LogSink

Handler = Callable[[list[Any]], None]


class CollectorBridge:
    def __init__(
        self, loop: asyncio.AbstractEventLoop, log: LogSink, *, max_pending: int = 10_000
    ) -> None:
        self._loop = loop
        self._log = log
        self._max_pending = max_pending
        self._lock = threading.Lock()
        self._handlers: dict[str, Handler] = {}  # insertion order = drain order
        self._queues: dict[str, deque[Any]] = {}
        self._dropped: dict[str, int] = {}
        self._scheduled = False

    def register(self, name: str, handler: Handler) -> Callable[[Any], None]:
        """Add a source; returns its ``post(item)``, callable from any thread."""
        with self._lock:
            if name in self._handlers:
                raise ValueError(f"collector source {name!r} is already registered")
            self._handlers[name] = handler
            self._queues[name] = deque()

        def post(item: Any) -> None:
            self._post(name, item)

        return post

    def _post(self, name: str, item: Any) -> None:
        with self._lock:
            queue = self._queues[name]
            queue.append(item)
            if len(queue) > self._max_pending:
                queue.popleft()
                self._dropped[name] = self._dropped.get(name, 0) + 1
            if self._scheduled:
                return
            self._scheduled = True
        try:
            self._loop.call_soon_threadsafe(self._drain)
        except RuntimeError:  # loop closed (shutdown): nothing will consume the items
            pass

    def _drain(self) -> None:
        with self._lock:
            self._scheduled = False
            batches = {name: queue for name, queue in self._queues.items() if queue}
            for name in batches:
                self._queues[name] = deque()
            dropped, self._dropped = self._dropped, {}
            handlers = list(self._handlers.items())
        for name, handler in handlers:
            count = dropped.get(name, 0)
            if count:
                self._log.emit("system", event="collector.dropped", source=name, count=count)
            items = batches.get(name)
            if not items:
                continue
            try:
                handler(list(items))
            except Exception as exc:
                self._log.emit(
                    "system", event="collector.handler_failed", source=name, error=repr(exc)
                )
