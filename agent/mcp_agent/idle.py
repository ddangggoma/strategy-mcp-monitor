"""Turn the session's idle seconds (``GetLastInputInfo``) into ``idle`` / ``active`` transitions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mcp_agent.sender import iso


class IdleTracker:
    def __init__(self, threshold_sec: float = 300) -> None:
        self._threshold = threshold_sec
        self._idle = False
        self._last = 0.0

    def update(self, idle_sec: float, at: datetime) -> dict[str, Any] | None:
        if not self._idle:
            if idle_sec >= self._threshold:
                self._idle, self._last = True, idle_sec
                return {"type": "idle", "at": iso(at), "idle_sec": int(idle_sec)}
            return None
        if idle_sec < self._last:  # input arrived since the last sample
            self._idle = False
            return {"type": "active", "at": iso(at), "idle_sec": int(self._last)}
        self._last = idle_sec
        return None
