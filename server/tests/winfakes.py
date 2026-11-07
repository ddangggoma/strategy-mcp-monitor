"""Fakes and helpers for the Windows collection tests (later tasks add their fakes here)."""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Literal

from app.win.launch import LaunchSpec
from app.win.peer import PeerInfo
from app.win.wmi import ProcessEvent
from app.win.wts import WtsSnapshot


class ListLog:
    """A ``LogSink`` that keeps ``(cat, at, fields)`` tuples in memory."""

    def __init__(self) -> None:
        self.events: list[tuple[str, datetime | None, dict[str, Any]]] = []

    def emit(self, cat: str, *, at: datetime | None = None, **fields: Any) -> None:
        self.events.append((cat, at, fields))

    emit_threadsafe = emit  # F09: the same tuple, from any thread (list.append is atomic)


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


class FakeLookup:
    """A ``ProcessLookup`` over a ``{pid: (exe, cmdline, user)}`` table; other pids → all None.
    ``calls`` records each looked-up pid."""

    def __init__(self, table: dict[int, tuple[str | None, str | None, str | None]]) -> None:
        self.table = dict(table)
        self.calls: list[int] = []

    def details(self, pid: int) -> tuple[str | None, str | None, str | None]:
        self.calls.append(pid)
        return self.table.get(pid, (None, None, None))


class FakeProcessSource:
    """A ``ProcessEventSource`` fed by the test.

    Each kind has one queue shared by every watch of that kind: ``next`` returns its items in order
    (an ``Exception`` among them is raised instead) and ``None`` after a 10 ms wait once it is
    empty. ``fail_watch(kind, *errors)`` makes the next ``watch(kind)`` calls raise those errors.
    ``watches`` keeps every watch handed out."""

    def __init__(
        self,
        start: Sequence[ProcessEvent | Exception] = (),
        stop: Sequence[ProcessEvent | Exception] = (),
        mode: str = "poll",
    ) -> None:
        self.mode = mode
        self.watches: list[FakeProcessWatch] = []
        self._lock = threading.Lock()
        self._items: dict[str, deque[ProcessEvent | Exception]] = {
            "start": deque(start), "stop": deque(stop),
        }
        self._watch_errors: dict[str, deque[Exception]] = {"start": deque(), "stop": deque()}
        self._calls: dict[str, int] = {"start": 0, "stop": 0}

    def fail_watch(self, kind: str, *errors: Exception) -> None:
        with self._lock:
            self._watch_errors[kind].extend(errors)

    def watch_count(self, kind: str) -> int:
        """How many times ``watch(kind)`` was called (failed calls included)."""
        with self._lock:
            return self._calls[kind]

    def watch(self, kind: Literal["start", "stop"]) -> FakeProcessWatch:
        with self._lock:
            self._calls[kind] += 1
            errors = self._watch_errors[kind]
            if errors:
                raise errors.popleft()
            w = FakeProcessWatch(self, kind)
            self.watches.append(w)
            return w

    def _take(self, kind: str) -> ProcessEvent | Exception | None:
        with self._lock:
            items = self._items[kind]
            return items.popleft() if items else None


class FakeProcessWatch:
    def __init__(self, source: FakeProcessSource, kind: str) -> None:
        self._source = source
        self.kind = kind
        self.mode: Literal["trace", "poll"] = "trace" if source.mode == "trace" else "poll"
        self.closed = False

    def next(self, timeout_ms: int) -> ProcessEvent | None:
        item = self._source._take(self.kind)
        if isinstance(item, Exception):
            raise item
        if item is None:
            time.sleep(min(timeout_ms, 10) / 1000)
        return item

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    """An ``AgentProcess``: runs until ``exit(code)``; ``kill()`` sets ``killed`` and the next
    ``poll()`` returns 1 (unless it had already exited). ``kill_threads``: the thread of each kill."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.killed = False
        self.kill_threads: list[int] = []
        self._code: int | None = None

    def exit(self, code: int) -> None:
        self._code = code

    def poll(self) -> int | None:
        return self._code

    def kill(self) -> None:
        self.kill_threads.append(threading.get_ident())
        self.killed = True
        if self._code is None:
            self._code = 1


class FakeLauncher:
    """An ``AgentLauncher`` that records each ``LaunchSpec`` and hands out ``FakeProcess``es with
    pids 1000, 1001, … . ``fail_next`` is raised by the next ``launch`` (once; no spec recorded).
    ``threads``: the thread of each ``launch`` call."""

    name = "fake"

    def __init__(self) -> None:
        self.specs: list[LaunchSpec] = []
        self.procs: list[FakeProcess] = []
        self.fail_next: Exception | None = None
        self.threads: list[int] = []

    def launch(self, spec: LaunchSpec) -> FakeProcess:
        self.threads.append(threading.get_ident())
        if self.fail_next is not None:
            error, self.fail_next = self.fail_next, None
            raise error
        self.specs.append(spec)
        proc = FakeProcess(1000 + len(self.procs))
        self.procs.append(proc)
        return proc
