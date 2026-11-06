"""Fakes and helpers for the Windows collection tests (later tasks add their fakes here)."""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.win.peer import PeerInfo
from app.win.wts import WtsSnapshot


class ListLog:
    """A ``LogSink`` that keeps ``(cat, at, fields)`` tuples in memory."""

    def __init__(self) -> None:
        self.events: list[tuple[str, datetime | None, dict[str, Any]]] = []

    def emit(self, cat: str, *, at: datetime | None = None, **fields: Any) -> None:
        self.events.append((cat, at, fields))


async def eventually(pred: Callable[[], bool], timeout: float = 5.0, step: float = 0.01) -> None:
    """Wait (yielding to the loop) until ``pred()`` is true; ``AssertionError`` after ``timeout``."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not pred():
        if loop.time() >= deadline:
            raise AssertionError(f"condition not met within {timeout}s")
        await asyncio.sleep(step)


class FakePeerResolver:
    """A ``PeerResolver`` that returns ``info`` for any peer and records each call's arguments."""

    def __init__(self, info: PeerInfo | None) -> None:
        self.info = info
        self.calls: list[tuple[str, int, int]] = []

    def resolve(self, client_ip: str, client_port: int, server_port: int) -> PeerInfo | None:
        self.calls.append((client_ip, client_port, server_port))
        return self.info


class FakeEventLogSource:
    """An ``EventLogSource`` fed by the test.

    ``queue(channel, *batches)`` adds what successive ``next()`` calls return (an ``Exception`` in
    the list is raised instead); the queue belongs to the channel, so a reopened subscription
    continues where the last one stopped. ``fail_open(channel, *errors)`` makes the next opens of
    that channel raise those errors in order. ``latest`` answers ``latest_record_id``; ``opened``
    records each successful ``open`` as ``(channel, xpath, after_record_id)``."""

    def __init__(self) -> None:
        self.latest: dict[str, int] = {}
        self.opened: list[tuple[str, str, int | None]] = []
        self._lock = threading.Lock()
        self._batches: dict[str, deque[list[str] | Exception]] = {}
        self._open_errors: dict[str, deque[Exception]] = {}

    def queue(self, channel: str, *batches: list[str] | Exception) -> None:
        with self._lock:
            self._batches.setdefault(channel, deque()).extend(batches)

    def fail_open(self, channel: str, *errors: Exception) -> None:
        with self._lock:
            self._open_errors.setdefault(channel, deque()).extend(errors)

    def latest_record_id(self, channel: str) -> int | None:
        return self.latest.get(channel)

    def open(self, channel: str, xpath: str, after_record_id: int | None) -> FakeSubscription:
        with self._lock:
            errors = self._open_errors.get(channel)
            if errors:
                raise errors.popleft()
            self.opened.append((channel, xpath, after_record_id))
        return FakeSubscription(self, channel)

    def _take(self, channel: str) -> list[str] | Exception | None:
        with self._lock:
            batches = self._batches.get(channel)
            return batches.popleft() if batches else None


class FakeSubscription:
    def __init__(self, source: FakeEventLogSource, channel: str) -> None:
        self._source = source
        self._channel = channel
        self.closed = False

    def next(self, timeout_ms: int) -> list[str]:
        batch = self._source._take(self._channel)
        if isinstance(batch, Exception):
            raise batch
        if batch is None:
            time.sleep(min(timeout_ms, 10) / 1000)
            return []
        return list(batch)

    def close(self) -> None:
        self.closed = True


class FakeWtsSource:
    """A ``WtsSource`` that replays ``items`` in order (raising the exceptions among them) and then
    keeps returning the last item. ``calls`` counts ``snapshot()`` calls."""

    def __init__(self, items: list[WtsSnapshot | Exception]) -> None:
        if not items:
            raise ValueError("FakeWtsSource needs at least one item")
        self.items = list(items)
        self.calls = 0

    def snapshot(self) -> WtsSnapshot:
        item = self.items[min(self.calls, len(self.items) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item
