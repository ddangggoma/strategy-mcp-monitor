"""Turns WTS snapshots into RDP connections (open/close), session log lines and board sessions.

Loop thread only: the collector thread hands snapshots over through the ``CollectorBridge``.
A session's identity is ``(session_id, logon_at)`` (V9): the same id with another logon time is
a new logon (Windows reuses ids). Nothing here assumes ``connected_at >= logon_at`` (the console
session reports its connect time before its logon time).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal

from app.clock import Clock, to_kst_iso
from app.logstore.writer import LogSink
from app.monitor.bus import BoardBus
from app.sessions.history import Connection, SessionHistory
from app.win.wts import WtsSession, WtsSnapshot

RDP_KEYS = frozenset({
    "session_id", "user", "domain", "client_name", "client_ip", "reverse_dns", "logon_at",
    "connected_at", "state", "idle_sec", "resolution", "notice_acknowledged", "connection_id",
    "client_build", "protocol", "first_seen_ip", "first_seen_device",
})

WTS_FAILURE_LOG_EVERY_SEC = 60


@dataclass(frozen=True)
class Opened:
    connection: Connection
    session: WtsSession


@dataclass(frozen=True)
class Closed:
    connection_id: int
    session_id: int
    reason: Literal["disconnect", "logoff", "reconnected"]
    at: datetime


@dataclass(frozen=True)
class LockChanged:
    session_id: int
    locked: bool
    at: datetime


Change = Opened | Closed | LockChanged


@dataclass(frozen=True)
class SessionContext:
    session_id: int
    user: str
    domain: str | None
    client_ip: str | None
    client_name: str | None
    connection_id: int | None

    @property
    def account(self) -> str:
        return f"{self.domain}\\{self.user}" if self.domain else self.user


def _account(user: str, domain: str | None) -> str:
    return f"{domain}\\{user}" if domain else user


def _iso(dt: datetime | None) -> str | None:
    return to_kst_iso(dt) if dt is not None else None


@dataclass
class _Tracked:
    """One watched session identity and its open connection (open ⇔ last seen ``active``)."""

    session: WtsSession
    conn: Connection | None = None
    prior: bool = False
    """True when the identity was there at the first snapshot or already had a connection:
    becoming active again is then a reconnect, not a logon."""
    notice: bool | None = None

    @property
    def identity(self) -> tuple[int, datetime | None]:
        return (self.session.session_id, self.session.logon_at)


class SessionTracker:
    def __init__(
        self,
        history: SessionHistory,
        clock: Clock,
        log: LogSink,
        bus: BoardBus,
        *,
        collect_console: bool = False,
    ) -> None:
        self._history = history
        self._clock = clock
        self._log = log
        self._bus = bus
        self._collect_console = collect_console
        self._tracked: dict[int, _Tracked] = {}
        self._listeners: list[Callable[[Change], None]] = []
        self._snap_at: datetime | None = None
        self._last_failure_log: datetime | None = None
        self._published: list[dict[str, Any]] | None = None
        self.ready = False

    # --- lifecycle -------------------------------------------------------------------------

    def start(self) -> int:
        """End the connections a previous run left open (``service_stop``); returns the count."""
        return self._history.close_dangling(self._clock.now())

    def add_listener(self, fn: Callable[[Change], None]) -> None:
        self._listeners.append(fn)

    def _watched(self, s: WtsSession) -> bool:
        if s.user == "":
            return False
        return s.protocol == "rdp" or (self._collect_console and s.protocol == "console")

    # --- snapshots -------------------------------------------------------------------------

    def apply(self, snap: WtsSnapshot) -> list[Change]:
        first = not self.ready
        at = snap.at
        current = {s.session_id: s for s in snap.sessions if self._watched(s)}
        changes: list[Change] = []
        for sid in sorted(self._tracked.keys() | current.keys()):
            prev = self._tracked.get(sid)
            new = current.get(sid)
            if prev is not None and (new is None or (new.session_id, new.logon_at) != prev.identity):
                self._logoff(prev, at, changes)
                del self._tracked[sid]
                prev = None
            if new is None:
                continue
            if prev is None:
                tracked = _Tracked(session=new, prior=first)
                self._tracked[sid] = tracked
                if new.state == "active":
                    self._open(tracked, new, "existing" if first else "logon", at, changes)
                continue
            self._update(prev, new, at, changes)
        self._snap_at = at
        self.ready = True
        self._notify(changes)
        self._publish()
        return changes

    def _update(self, t: _Tracked, new: WtsSession, at: datetime, changes: list[Change]) -> None:
        old = t.session
        if t.conn is None:
            t.session = new
            if new.state == "active":
                self._open(t, new, "reconnect" if t.prior else "logon", at, changes)
            return
        if new.state != "active":
            self._close(t, "disconnect", at, changes)
            t.session = new
            return
        if new.connected_at != old.connected_at:  # a reconnect whose disconnect fell between polls
            self._close(t, "reconnected", at, changes)
            t.session = new
            self._open(t, new, "reconnect", at, changes)
            return
        t.session = new
        if isinstance(old.locked, bool) and isinstance(new.locked, bool) and old.locked != new.locked:
            changes.append(LockChanged(new.session_id, new.locked, at))
            self._log_line("unlock" if not new.locked else "lock", at, new, t.conn)

    def _open(self, t: _Tracked, s: WtsSession, kind: str, at: datetime, changes: list[Change]) -> None:
        conn = self._history.open(s, kind, at)
        t.conn = conn
        t.prior = True
        t.notice = None
        changes.append(Opened(conn, s))
        self._log_line("connect", at, s, conn, kind=kind)

    def _close(
        self, t: _Tracked, reason: Literal["disconnect", "logoff", "reconnected"], at: datetime,
        changes: list[Change],
    ) -> None:
        conn = t.conn
        assert conn is not None
        self._history.close(conn.id, at, reason)
        t.conn = None
        t.notice = None
        changes.append(Closed(conn.id, conn.session_id, reason, at))
        if reason == "reconnected":  # the disconnect fell between two polls: log it as one
            self._log_line("disconnect", at, t.session, conn, reason="reconnected")
        else:
            self._log_line(reason, at, t.session, conn)

    def _logoff(self, t: _Tracked, at: datetime, changes: list[Change]) -> None:
        if t.conn is not None:
            self._close(t, "logoff", at, changes)
        else:
            self._log_line("logoff", at, t.session, None)

    def _log_line(
        self, event: str, at: datetime, s: WtsSession, conn: Connection | None, **extra: Any
    ) -> None:
        """A ``session`` line; the client fields come from the connection when there is one."""
        src: WtsSession | Connection = conn if conn is not None else s
        self._log.emit(
            "session",
            at=at,
            event=event,
            **extra,
            connection_id=conn.id if conn is not None else None,
            session_id=s.session_id,
            user=_account(src.user, src.domain),
            domain=src.domain,
            client_ip=src.client_ip,
            client_name=src.client_name,
            client_build=src.client_build,
            protocol=src.protocol,
            resolution=src.resolution,
            source="wts",
        )

    def _notify(self, changes: list[Change]) -> None:
        for change in changes:
            for fn in list(self._listeners):
                try:
                    fn(change)
                except Exception as exc:  # one broken listener must not stop the others
                    self._log.emit("system", event="sessions.listener_failed", error=repr(exc))

    def failed(self, error: str) -> None:
        """A WTS read failed: keep the last state, log at most once a minute."""
        now = self._clock.now()
        last = self._last_failure_log
        if last is not None and (now - last).total_seconds() < WTS_FAILURE_LOG_EVERY_SEC:
            return
        self._last_failure_log = now
        self._log.emit("system", event="sessions.wts_failed", error=error)

    # --- board -----------------------------------------------------------------------------

    def _idle_sec(self, s: WtsSession) -> int | None:
        if s.last_input_at is None or self._snap_at is None:
            return None
        return max(0, int((self._snap_at - s.last_input_at).total_seconds()))

    def board_sessions(self) -> list[dict[str, Any]] | None:
        """Active (incl. locked) watched sessions for the board, by session id; None before ready."""
        if not self.ready:
            return None
        out: list[dict[str, Any]] = []
        for sid in sorted(self._tracked):
            t = self._tracked[sid]
            s, conn = t.session, t.conn
            if s.state != "active" or conn is None:
                continue
            out.append({
                "session_id": s.session_id,
                "user": s.user,
                "domain": s.domain,
                "client_name": s.client_name,
                "client_ip": s.client_ip,
                "reverse_dns": conn.reverse_dns,
                "logon_at": _iso(s.logon_at),
                "connected_at": _iso(conn.connected_at),
                "state": "locked" if s.locked else "active",
                "idle_sec": self._idle_sec(s),
                "resolution": s.resolution,
                "notice_acknowledged": t.notice,
                "connection_id": conn.id,
                "client_build": s.client_build,
                "protocol": s.protocol,
                "first_seen_ip": conn.first_seen_ip,
                "first_seen_device": conn.first_seen_device,
            })
        return out

    def _publish(self) -> None:
        """Publish ``sessions`` when what the board shows changed (idle time counts per minute, V10)."""
        sessions = self.board_sessions()
        if sessions is None:
            return
        key = [
            {**s, "idle_sec": s["idle_sec"] // 60 if s["idle_sec"] is not None else None}
            for s in sessions
        ]
        if key == self._published:
            return
        self._published = key
        self._bus.publish("sessions", {"sessions": sessions})

    def set_notice_state(self, connection_id: int, acknowledged: bool | None) -> None:
        """The notice state of an open connection (unknown or closed connections are ignored)."""
        t = self._by_connection(connection_id)
        if t is None:
            return
        t.notice = acknowledged
        self._publish()

    def set_reverse_dns(self, connection_id: int, name: str | None) -> None:
        """Store a reverse-DNS name on the history row, and on the board while the connection is open."""
        self._history.set_reverse_dns(connection_id, name)
        t = self._by_connection(connection_id)
        if t is None or t.conn is None:
            return
        t.conn = replace(t.conn, reverse_dns=name)
        self._publish()

    def _by_connection(self, connection_id: int) -> _Tracked | None:
        for t in self._tracked.values():
            if t.conn is not None and t.conn.id == connection_id:
                return t
        return None

    # --- queries ---------------------------------------------------------------------------

    def current(self) -> list[dict[str, Any]]:
        """Every watched session, disconnected ones included, by session id."""
        out: list[dict[str, Any]] = []
        for sid in sorted(self._tracked):
            t = self._tracked[sid]
            s = t.session
            if s.state == "active":
                state = "locked" if s.locked else "active"
            elif s.state == "disconnected":
                state = "disconnected"
            else:
                state = "connected"
            out.append({
                "session_id": s.session_id,
                "user": s.user,
                "domain": s.domain,
                "state": state,
                "client_name": s.client_name,
                "client_ip": s.client_ip,
                "protocol": s.protocol,
                "logon_at": _iso(s.logon_at),
                "connected_at": _iso(s.connected_at),
                "disconnected_at": _iso(s.disconnected_at),
                "idle_sec": self._idle_sec(s),
                "connection_id": t.conn.id if t.conn is not None else None,
            })
        return out

    def context(self, session_id: int) -> SessionContext | None:
        """The session's user and client, while the watched session exists (connected or not)."""
        t = self._tracked.get(session_id)
        if t is None:
            return None
        s = t.session
        return SessionContext(
            session_id=s.session_id,
            user=s.user,
            domain=s.domain,
            client_ip=s.client_ip,
            client_name=s.client_name,
            connection_id=t.conn.id if t.conn is not None else None,
        )

    def by_user(self, user: str, domain: str | None) -> SessionContext | None:
        """The only watched session of that account (case-insensitive; ``domain=None`` matches any)."""
        u = user.casefold()
        d = domain.casefold() if domain is not None else None
        hits = [
            sid for sid, t in self._tracked.items()
            if t.session.user.casefold() == u
            and (d is None or (t.session.domain or "").casefold() == d)
        ]
        return self.context(hits[0]) if len(hits) == 1 else None

    def connection_of(self, session_id: int) -> int | None:
        t = self._tracked.get(session_id)
        return t.conn.id if t is not None and t.conn is not None else None
