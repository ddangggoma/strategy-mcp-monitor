from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.clock import KST, Clock, to_kst_iso


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
            by_day[day].append(json.dumps(event, ensure_ascii=False, default=str))
        if not by_day:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        for day, lines in by_day.items():
            with open(self._dir / f"{day}.jsonl", "a", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(lines) + "\n")


class LogWriter:
    """Non-blocking event sink: emit() queues, a background task writes batches."""

    def __init__(
        self,
        daily: DailyJsonlWriter,
        clock: Clock,
        flush_interval: float = 0.2,
        max_batch: int = 500,
    ) -> None:
        self._daily = daily
        self._clock = clock
        self._flush_interval = flush_interval
        self._max_batch = max_batch
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()
        self._retry: list[dict[str, Any]] | None = None  # failed batch awaiting its one retry
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._stopped = False

    def emit(self, cat: str, **fields: Any) -> None:
        """Queue an event stamped with the current time. Never raises, never blocks."""
        try:
            if self._stopped:
                return
            event: dict[str, Any] = {"ts": to_kst_iso(self._clock.now()), "cat": cat}
            event.update((k, v) for k, v in fields.items() if k != "ts")
            self._queue.put_nowait(event)
            if self._queue.qsize() >= self._max_batch:
                self._wake.set()
        except Exception as exc:
            _warn(f"emit failed: {exc!r}")

    async def start(self) -> None:
        if self._task is None and not self._stopped:
            self._task = asyncio.create_task(self._run(), name="log-writer")

    async def flush(self) -> None:
        """Wait until everything queued so far has been written (or given up on)."""
        await self._drain()

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopping = True
        self._wake.set()
        if self._task is not None:
            await self._task
        # Bounded: each pass either writes everything, or consumes a retry slot.
        for _ in range(3):
            if self._queue.empty() and self._retry is None:
                break
            await self._drain()
        self._stopped = True

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await asyncio.wait_for(self._wake.wait(), self._flush_interval)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            try:
                await self._drain()
            except Exception as exc:  # keep the background task alive no matter what
                _warn(f"drain failed: {exc!r}")

    def _take_batch(self) -> list[dict[str, Any]]:
        batch: list[dict[str, Any]] = []
        while len(batch) < self._max_batch:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    async def _drain(self) -> None:
        async with self._lock:
            if self._retry is not None:
                batch, self._retry = self._retry, None
                try:
                    await asyncio.to_thread(self._daily.write_batch, batch)
                except Exception as exc:
                    _warn(f"retry failed, dropping {len(batch)} log event(s): {exc!r}")
            while True:
                batch = self._take_batch()
                if not batch:
                    return
                try:
                    await asyncio.to_thread(self._daily.write_batch, batch)
                except Exception as exc:
                    _warn(f"write failed, will retry {len(batch)} log event(s) once: {exc!r}")
                    self._retry = batch
                    return
