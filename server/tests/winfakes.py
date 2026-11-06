"""Fakes and helpers for the Windows collection tests (later tasks add their fakes here)."""

from __future__ import annotations

import asyncio
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
