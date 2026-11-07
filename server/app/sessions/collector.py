"""The WTS polling thread: snapshots (or failures) go to the loop through a ``CollectorBridge`` post.

V6: polling every ``interval_sec`` (0.5 s) is the main path; ``nudge()`` wakes the thread at once
(the Plan 5 service host calls it on ``SERVICE_CONTROL_SESSIONCHANGE``). The thread never touches
the tracker, the database or the log writer: it only calls ``post``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.clock import Clock
from app.win.wts import WtsSnapshot, WtsSource


@dataclass(frozen=True)
class WtsFailure:
    error: str
    """``repr`` of the exception the source raised."""
    at: datetime


class SessionCollector:
    THREAD_NAME = "wts-collector"

    def __init__(
        self,
        source: WtsSource,
        post: Callable[[WtsSnapshot | WtsFailure], None],
        clock: Clock,
        *,
        interval_sec: float = 0.5,
    ) -> None:
        self._source = source
        self._post = post
        self._clock = clock
        self._interval_sec = interval_sec
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("SessionCollector already started")
        self._thread = threading.Thread(target=self._run, name=self.THREAD_NAME, daemon=True)
        self._thread.start()

    def nudge(self) -> None:
        """Take the next snapshot now instead of at the end of the current wait."""
        self._wake.set()

    def stop(self, timeout: float = 2.0) -> None:
        """Ask the thread to end and wait up to ``timeout`` (a snapshot in progress finishes first)."""
        self._stopping.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        while not self._stopping.is_set():
            item: WtsSnapshot | WtsFailure
            try:
                item = self._source.snapshot()
            except Exception as exc:  # WtsError and anything unexpected: report, keep polling
                item = WtsFailure(repr(exc), self._clock.now())
            if self._stopping.is_set():
                return
            self._post(item)
            self._wake.wait(self._interval_sec)
            self._wake.clear()
