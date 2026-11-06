"""Buffer events and deliver them in batches to ``POST /api/agent/events``."""

from __future__ import annotations

import sys
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from mcp_agent.client import ServerUnavailable
from mcp_agent.coalesce import RawWinEvent

KST = timezone(timedelta(hours=9))
EVENTS_PATH = "/api/agent/events"
TITLE_MAX = 512  # the server's WindowEventIn limits
EXE_MAX = 260


def iso(at: datetime) -> str:
    return at.astimezone(KST).isoformat(timespec="milliseconds")


def _text(s: str, limit: int) -> str:
    # Window titles can hold lone surrogates, which UTF-8 JSON cannot carry.
    return s.encode("utf-8", "replace").decode("utf-8")[:limit]


def to_event(e: RawWinEvent) -> dict[str, Any]:
    return {"type": e.kind, "at": iso(e.at), "pid": e.pid, "exe": None if e.exe is None else _text(e.exe, EXE_MAX),
            "title": _text(e.title, TITLE_MAX)}


def to_payload(items: list[RawWinEvent | dict[str, Any]]) -> dict[str, Any]:
    return {"events": [to_event(x) if isinstance(x, RawWinEvent) else x for x in items]}


class _Poster(Protocol):
    def post(self, path: str, body: dict[str, Any] | None = None, *,
             verified_only: bool = False) -> dict[str, Any] | None: ...


class EventSender:
    """Keeps at most ``buffer_max`` events (the oldest go first, counted in ``dropped``).

    ``flush`` stops at the first ``ServerUnavailable`` and keeps the rest for the next try;
    ``AgentRejected`` propagates; a batch the server refuses as invalid (other 4xx) is dropped
    rather than retried forever."""

    def __init__(self, client: _Poster, *, events_max: int = 200, buffer_max: int = 2000) -> None:
        self._client = client
        self._events_max = max(1, events_max)
        self._buffer: deque[RawWinEvent | dict[str, Any]] = deque()
        self._buffer_max = buffer_max
        self._lock = threading.Lock()
        self.dropped = 0

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._buffer)

    def add(self, item: RawWinEvent | dict[str, Any]) -> None:
        with self._lock:
            if len(self._buffer) >= self._buffer_max:
                self._buffer.popleft()
                self.dropped += 1
            self._buffer.append(item)

    def flush(self) -> None:
        with self._lock:
            while self._buffer:
                batch = [self._buffer[i] for i in range(min(self._events_max, len(self._buffer)))]
                try:
                    # Window titles only go to a server that proved itself since the last outage (I1).
                    self._client.post(EVENTS_PATH, to_payload(batch), verified_only=True)
                except ServerUnavailable:
                    return
                except RuntimeError as e:
                    self.dropped += len(batch)
                    print(f"mcp_agent: dropped {len(batch)} events: {e}", file=sys.stderr)
                for _ in batch:
                    self._buffer.popleft()
