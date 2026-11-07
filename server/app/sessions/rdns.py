"""Reverse DNS for RDP client addresses (V22): off the loop, time-limited, cached.

A connection is shown at once; the name is filled in when (and if) the lookup answers within
``timeout_sec``. Answers and failures are cached for ``ttl_sec`` (at most ``max_entries``: expired
entries go first, then the oldest); a timeout is not cached, so the next connection from that
address tries again.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Callable
from datetime import datetime, timedelta

from app.clock import Clock

Lookup = Callable[[str], tuple[str, list[str], list[str]]]


class ReverseDns:
    def __init__(
        self,
        lookup: Lookup = socket.gethostbyaddr,
        *,
        timeout_sec: float = 2.0,
        ttl_sec: float = 600,
        max_entries: int = 4096,
        clock: Clock,
    ) -> None:
        self._lookup = lookup
        self._timeout_sec = timeout_sec
        self._ttl = timedelta(seconds=ttl_sec)
        self._clock = clock
        self._max_entries = max(1, max_entries)
        self._cache: dict[str, tuple[str | None, datetime]] = {}

    async def resolve(self, ip: str) -> str | None:
        """The PTR name of ``ip``; None when ``ip`` is not an address, unknown, or too slow."""
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return None
        now = self._clock.now()
        cached = self._cache.get(ip)
        if cached is not None and cached[1] > now:
            return cached[0]
        try:
            host, _aliases, _addrs = await asyncio.wait_for(
                asyncio.to_thread(self._lookup, ip), self._timeout_sec
            )
        except TimeoutError:
            return None  # not cached: a slow resolver may answer next time
        except OSError:  # socket.herror / gaierror: no name for this address
            name = None
        else:
            name = host or None
        now = self._clock.now()
        self._cache.pop(ip, None)
        if len(self._cache) >= self._max_entries:
            self._cache = {k: v for k, v in self._cache.items() if v[1] > now}
            while len(self._cache) >= self._max_entries:
                del self._cache[next(iter(self._cache))]
        self._cache[ip] = (name, now + self._ttl)
        return name
