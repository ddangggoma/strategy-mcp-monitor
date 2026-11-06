"""Fakes and helpers for the Windows collection tests (later tasks add their fakes here)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any


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
