"""Bypass (tamper) detection hub (V19): every detector reports here, so each event is written to the
``tamper`` log, kept in a small in-memory ring for ``GET /api/tamper/recent`` and pushed to logged-in
board subscribers as the SSE ``tamper`` event (never to anonymous ones)."""
from __future__ import annotations

import itertools
from collections import deque
from datetime import datetime
from typing import Any

from app.clock import Clock, to_kst_iso
from app.logstore.writer import LogSink
from app.monitor.bus import BoardBus


class TamperMonitor:
    """Loop thread only (collector threads go through the ``CollectorBridge``)."""

    def __init__(self, log: LogSink, bus: BoardBus, clock: Clock, *, keep: int = 200) -> None:
        self._log = log
        self._bus = bus
        self._clock = clock
        self._ring: deque[dict[str, Any]] = deque(maxlen=keep)

    def report(self, event: str, *, at: datetime | None = None, **fields: Any) -> dict[str, Any]:
        """Record one tamper event; ``at`` is the event time (default: now). Returns the record."""
        record: dict[str, Any] = {"at": to_kst_iso(at or self._clock.now()), "event": event, **fields}
        self._log.emit("tamper", at=at, event=event, **fields)
        self._ring.append(record)
        self._bus.publish("tamper", record, public=False)
        return record

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """The newest ``limit`` records, newest first."""
        return [dict(r) for r in itertools.islice(reversed(self._ring), limit)]
