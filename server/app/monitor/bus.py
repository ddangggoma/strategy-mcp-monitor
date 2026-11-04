from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field

MAX_STREAMS = 100
MAX_PENDING_EVENTS = 100


class StreamLimitError(Exception):
    pass


@dataclass(eq=False)
class Subscription:
    """One SSE consumer. ``authed`` is fixed at subscribe time and gates non-public events."""

    authed: bool = False
    dirty: set[int] = field(default_factory=set)
    events: deque[tuple[str, dict]] = field(
        default_factory=lambda: deque(maxlen=MAX_PENDING_EVENTS)
    )
    wake: asyncio.Event = field(default_factory=asyncio.Event)


class BoardBus:
    """Fan-out of board changes to SSE subscribers.

    Publishing never blocks or awaits: a subscriber that falls behind loses its oldest
    queued events (``events`` is bounded) while ``dirty`` is just a set of MCP ids.
    Call from the event-loop thread only.
    """

    def __init__(self, max_streams: int = MAX_STREAMS) -> None:
        self._max_streams = max_streams
        self._subs: list[Subscription] = []

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def subscribe(self, authed: bool = False) -> Subscription:
        if len(self._subs) >= self._max_streams:
            raise StreamLimitError
        sub = Subscription(authed=authed)
        self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        """Idempotent, so it is safe to call from a ``finally`` block."""
        try:
            self._subs.remove(sub)
        except ValueError:
            pass

    def mark_dirty(self, mcp_id: int) -> None:
        for sub in self._subs:
            sub.dirty.add(mcp_id)
            sub.wake.set()

    def publish(self, event: str, data: Mapping, *, public: bool = True) -> None:
        """Queue an event; with ``public=False`` only authenticated subscribers get it."""
        payload = dict(data)
        for sub in self._subs:
            if public or sub.authed:
                sub.events.append((event, payload))
                sub.wake.set()
