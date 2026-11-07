from __future__ import annotations

import asyncio
import functools
import json
import sys
import threading
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from app.clock import KST, Clock, to_kst_iso


class LogSink(Protocol):
    """Anything that takes log events like :meth:`LogWriter.emit` (loop thread only)."""

    def emit(self, cat: str, *, at: datetime | None = None, **fields: Any) -> None: ...


def _dumps(event: Mapping[str, Any]) -> str:
    """Serialize one event; on failure emit a fallback line so the event is still represented."""
    try:
        return json.dumps(event, ensure_ascii=False, default=str)
    except Exception as exc:
        try:
            detail = repr(event)
        except Exception:
            detail = f"<unrepresentable {type(event).__name__}>"
        _warn(f"unserializable log event ({exc!r}); writing fallback line")
        return json.dumps(
            {"ts": event["ts"], "cat": event["cat"], "_unserializable": detail, "_error": repr(exc)},
            ensure_ascii=False,
            default=str,
        )


def _warn(msg: str) -> None:
    try:
        print(f"[logstore] warning: {msg}", file=sys.stderr)
    except Exception:  # stderr itself may be unavailable; never raise from logging
        pass


class DailyJsonlWriter:
    """Appends events to ``<logs_dir>/YYYY-MM-DD.jsonl`` (day = event ``ts`` in KST)."""

    def __init__(self, logs_dir: Path) -> None:
        self._dir = Path(logs_dir)

    def write_batch(self, events: Sequence[Mapping[str, Any]]) -> None:
        by_day: dict[str, list[str]] = defaultdict(list)
        for event in events:
            day = datetime.fromisoformat(event["ts"]).astimezone(KST).strftime("%Y-%m-%d")
            if "cat" not in event:
                raise KeyError("cat")
            by_day[day].append(_dumps(event))
        if not by_day:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        for day, lines in by_day.items():
            # backslashreplace: a lone surrogate in a string must not fail the whole write
            with open(
                self._dir / f"{day}.jsonl", "a", encoding="utf-8", errors="backslashreplace", newline="\n"
            ) as f:
                f.write("\n".join(lines) + "\n")


class _DroppedReport(dict[str, Any]):
    """The ``logstore.dropped`` event. If it is lost too, the events it counted are counted again."""


def _event_count(events: Iterable[Mapping[str, Any]]) -> int:
    """How many emitted events ``events`` stand for (a dropped report stands for its count)."""
    return sum(e["count"] if isinstance(e, _DroppedReport) else 1 for e in events)


class LogWriter:
    """Non-blocking event sink: emit() queues, a background task writes batches.

    The queue is bounded (``max_queue``): when it is full the oldest event is dropped. Dropped
    events (queue overflow, or a batch whose retry failed too) are counted and reported with one
    ``system`` ``logstore.dropped`` event put at the front of the next batch; while writes keep
    failing that report is retried and, if lost, re-counted, so the count is written by the
    first write that succeeds again (even when no other event is waiting).
    """

    def __init__(
        self,
        daily: DailyJsonlWriter,
        clock: Clock,
        flush_interval: float = 0.2,
        max_batch: int = 500,
        max_queue: int = 100_000,
    ) -> None:
        self._daily = daily
        self._clock = clock
        self._flush_interval = flush_interval
        self._max_batch = max_batch
        self._max_queue = max_queue
        self._queue: deque[dict[str, Any]] = deque()
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()
        self._retry: list[dict[str, Any]] | None = None  # failed batch awaiting its one retry
        self._dropped = 0  # events lost since the last report
        self._full_warned = False  # "queue full" warned since the last written report
        self._listeners: list[Callable[[], None]] = []
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None  # saved by start() for emit_threadsafe
        self._loop_thread: int | None = None
        self._stopping = False
        self._stopped = False

    @property
    def pending(self) -> int:
        """Events queued or held for their retry (not yet written)."""
        return len(self._queue) + len(self._retry or ())

    @property
    def stopped(self) -> bool:
        return self._stopped

    def add_flush_listener(self, fn: Callable[[], None]) -> None:
        """Call ``fn()`` on the loop thread after every successful batch write, in registration order."""
        self._listeners.append(fn)

    def emit(self, cat: str, *, at: datetime | None = None, **fields: Any) -> None:
        """Queue an event stamped ``at`` (the event time) or else the current time.

        Never raises, never blocks. A ``ts`` key in ``fields`` is ignored. Not thread-safe
        (deque/asyncio.Event): call only on the event-loop thread; from other threads use
        :meth:`emit_threadsafe`.
        """
        try:
            if self._stopped:
                return
            stamp = at if at is not None else self._clock.now()
            event: dict[str, Any] = {"ts": to_kst_iso(stamp), "cat": cat}
            event.update((k, v) for k, v in fields.items() if k != "ts")
            while len(self._queue) >= self._max_queue:
                self._dropped += _event_count((self._queue.popleft(),))
                if not self._full_warned:
                    self._full_warned = True
                    _warn("log queue full; dropping oldest events")
            self._queue.append(event)
            if len(self._queue) >= self._max_batch:
                self._wake.set()
        except Exception as exc:
            _warn(f"emit failed: {exc!r}")

    def emit_threadsafe(self, cat: str, *, at: datetime | None = None, **fields: Any) -> None:
        """:meth:`emit` callable from any thread. Never raises.

        On the loop thread it emits directly (keeps order with plain ``emit`` calls); from other
        threads it schedules ``emit`` on the loop saved by :meth:`start`. Before ``start`` or
        after the loop has closed the event is dropped with a stderr warning.
        """
        try:
            loop = self._loop
            if loop is None:
                _warn("emit_threadsafe before start")
                return
            if threading.get_ident() == self._loop_thread:
                self.emit(cat, at=at, **fields)
                return
            try:
                loop.call_soon_threadsafe(functools.partial(self.emit, cat, at=at, **fields))
            except RuntimeError:
                _warn("emit_threadsafe after loop closed")
        except Exception as exc:
            _warn(f"emit_threadsafe failed: {exc!r}")

    async def start(self) -> None:
        if self._task is None and not self._stopped:
            self._loop = asyncio.get_running_loop()
            self._loop_thread = threading.get_ident()
            self._task = asyncio.create_task(self._run(), name="log-writer")

    async def flush(self) -> None:
        """Wait until everything queued so far has been written (or given up on)."""
        await self._drain()

    async def stop(self) -> None:
        """Write what is queued, then stop. Safe to cancel: the cleanup always runs.

        Whatever could not be written is reported on stderr. If ``stop()`` itself is cancelled,
        the background task is cancelled (not shielded), the cleanup runs, and the
        ``CancelledError`` propagates.
        """
        if self._stopped:
            return
        try:
            self._stopping = True
            self._wake.set()
            if self._task is not None:
                await self._task
            # Bounded: each pass either writes everything, or consumes a retry slot.
            for _ in range(3):
                if not self._queue and self._retry is None and self._dropped == 0:
                    break
                await self._drain()
        finally:
            try:
                task = self._task
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            finally:
                lost = self._dropped + _event_count(self._queue) + _event_count(self._retry or ())
                if lost > 0:
                    _warn(f"stop: {lost} log event(s) were not written")
                self._stopped = True

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await asyncio.wait_for(self._wake.wait(), self._flush_interval)
            except TimeoutError:
                pass
            self._wake.clear()
            try:
                await self._drain()
            except Exception as exc:  # keep the background task alive no matter what
                _warn(f"drain failed: {exc!r}")

    def _take_batch(self) -> list[dict[str, Any]]:
        return [self._queue.popleft() for _ in range(min(self._max_batch, len(self._queue)))]

    def _queue_drop_report(self) -> None:
        """Put the count of dropped events at the front of the next batch."""
        if self._dropped > 0:
            self._queue.appendleft(
                _DroppedReport(
                    ts=to_kst_iso(self._clock.now()), cat="system", event="logstore.dropped",
                    count=self._dropped,
                )
            )
            self._dropped = 0

    def _written(self, batch: Sequence[Mapping[str, Any]]) -> None:
        """After a successful write: re-arm the "queue full" warning, then notify the listeners."""
        if any(isinstance(e, _DroppedReport) for e in batch):
            self._full_warned = False
        for fn in self._listeners:
            try:
                fn()
            except Exception as exc:
                _warn(f"flush listener failed: {exc!r}")

    async def _drain(self) -> None:
        async with self._lock:
            if self._retry is not None:
                batch, self._retry = self._retry, None
                try:
                    await asyncio.to_thread(self._daily.write_batch, batch)
                except Exception as exc:
                    _warn(f"retry failed, dropping {len(batch)} log event(s): {exc!r}")
                    self._dropped += _event_count(batch)
                else:
                    self._written(batch)
            while True:
                self._queue_drop_report()
                batch = self._take_batch()
                if not batch:
                    return
                try:
                    await asyncio.to_thread(self._daily.write_batch, batch)
                except Exception as exc:
                    _warn(f"write failed, will retry {len(batch)} log event(s) once: {exc!r}")
                    self._retry = batch
                    return
                self._written(batch)
