from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field

MAX_STREAMS = 100
MAX_STREAMS_PER_IP = 5
MAX_PENDING_EVENTS = 100


class StreamLimitError(Exception):
    """The global stream cap is reached."""


class IpStreamLimitError(StreamLimitError):
    """One client address already holds its maximum number of streams."""


@dataclass(eq=False)
class Subscription:
    """One SSE consumer. ``authed`` is fixed at subscribe time and gates non-public events."""

    authed: bool = False
    ip: str | None = None
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

    def __init__(self, max_streams: int = MAX_STREAMS, max_per_ip: int = MAX_STREAMS_PER_IP) -> None:
        self._max_streams = max_streams
        self._max_per_ip = max_per_ip
        self._subs: list[Subscription] = []
        self._versions: dict[int, int] = {}

    def version(self, mcp_id: int) -> int:
        """How many times ``mcp_id`` was marked dirty: a shared board item is valid for one version."""
        return self._versions.get(mcp_id, 0)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def check_capacity(self, ip: str | None = None) -> None:
        """Raise if a subscription for ``ip`` would be refused now (a cheap pre-flight for routes)."""
        if len(self._subs) >= self._max_streams:
            raise StreamLimitError
        if ip is not None and sum(1 for s in self._subs if s.ip == ip) >= self._max_per_ip:
            raise IpStreamLimitError

    def subscribe(self, authed: bool = False, ip: str | None = None) -> Subscription:
        self.check_capacity(ip)
        sub = Subscription(authed=authed, ip=ip)
        self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        """Idempotent, so it is safe to call from a ``finally`` block."""
        try:
            self._subs.remove(sub)
        except ValueError:
            pass

    def mark_dirty(self, mcp_id: int) -> None:
        self._versions[mcp_id] = self._versions.get(mcp_id, 0) + 1
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
