"""Which RDP session a process belongs to, and the session fields every activity line carries.

Runs on the loop thread only (it reads the ``SessionTracker``).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.clock import Clock
from app.sessions.tracker import SessionContext
from app.win.ffi import process_session_id


class SessionLookup(Protocol):
    """The part of ``SessionTracker`` this module reads."""

    def by_user(self, user: str, domain: str | None) -> SessionContext | None: ...

    def context(self, session_id: int) -> SessionContext | None: ...


@dataclass(frozen=True)
class _Seen:
    session_id: int | None
    name: str | None
    at: datetime


class ActivityContext:
    def __init__(
        self,
        tracker: SessionLookup,
        clock: Clock,
        *,
        pid_session: Callable[[int], int | None] = process_session_id,
        ttl_sec: float = 300,
        max_pids: int = 50_000,
    ) -> None:
        self._tracker = tracker
        self._clock = clock
        self._pid_session = pid_session
        self._ttl = timedelta(seconds=ttl_sec)
        self._max_pids = max_pids
        self._pids: OrderedDict[int, _Seen] = OrderedDict()

    def remember(self, pid: int, session_id: int | None, name: str | None, at: datetime) -> None:
        """Cache a started process's session (LRU: the least recently remembered pid goes first)."""
        self._pids[pid] = _Seen(session_id, name, at)
        self._pids.move_to_end(pid)
        while len(self._pids) > self._max_pids:
            self._pids.popitem(last=False)

    def session_of(
        self, pid: int | None, *, user: str | None = None, domain: str | None = None
    ) -> int | None:
        """① the cache (within ``ttl_sec`` of the start) ② ``ProcessIdToSessionId``
        ③ the only tracked session of that account ④ None."""
        if pid is not None:
            seen = self._pids.get(pid)
            if (
                seen is not None
                and seen.session_id is not None
                and self._clock.now() - seen.at <= self._ttl
            ):
                return seen.session_id
            sid = self._pid_session(pid)
            if sid is not None:
                return sid
        if user:
            ctx = self._tracker.by_user(user, domain)
            if ctx is not None:
                return ctx.session_id
        return None

    def fields(self, session_id: int | None, *, user: str | None = None) -> dict[str, Any]:
        """``session_id``, ``user``, ``client_ip``, ``client_name``: the tracked session's account
        and client, else ``user`` as given and no client."""
        ctx = self._tracker.context(session_id) if session_id is not None else None
        if ctx is None:
            return {"session_id": session_id, "user": user, "client_ip": None, "client_name": None}
        return {
            "session_id": session_id,
            "user": ctx.account,
            "client_ip": ctx.client_ip,
            "client_name": ctx.client_name,
        }
