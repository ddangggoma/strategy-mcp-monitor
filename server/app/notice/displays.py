"""Notice displays: one per RDP connection, with the notice version pinned when it is created (V15).

Each showing attempt gets a fresh token (``issue``); the server keeps only its sha256, in memory,
and a newer token of the same display replaces the older one. The notice page reports with that
token that it was shown (``open`` → ``notice_shown``) and that the user confirmed it
(``acknowledge`` → ``notice_acknowledged``, with the time since the last showing). The request's
TCP peer session must be the display's session; a valid token used from another session is a
``notice_token_misuse`` tamper event (V16).

Call from the event-loop thread only (``Database.transaction`` rule).
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from app.activity.tamper import MISUSE_REPORT_SEC, TamperMonitor
from app.clock import Clock
from app.db import Database
from app.logstore.writer import LogSink
from app.notice.content import NoticeContent
from app.notice.store import NoticeStore
from app.sessions.history import Connection
from app.sessions.tracker import Change, Closed, Opened, SessionTracker

DisplayEvent = Literal["created", "acknowledged"]
CloseReason = Literal["acknowledged", "superseded", "logoff", "service_restart"]

_COLUMNS = (
    "id, connection_id, session_id, user, kind, version, created_at, attempts, first_shown_at,"
    " last_shown_at, acknowledged_at, ack_ms, closed_reason"
)
_IN_CHUNK = 500  # bound the number of SQL variables per query


class DisplayNotFoundError(Exception):
    """Unknown or superseded token, closed display, or a request from another session."""


@dataclass(frozen=True)
class Display:
    id: int
    connection_id: int
    session_id: int
    user: str  # DOMAIN\name (the session-context ``user`` of the log lines)
    kind: str
    version: int
    created_at: datetime
    attempts: int
    first_shown_at: datetime | None
    last_shown_at: datetime | None
    acknowledged_at: datetime | None
    ack_ms: int | None
    closed_reason: str | None


@dataclass(frozen=True)
class Ticket:
    display_id: int
    token: str
    attempt: int


@dataclass
class _Issued:
    """What the server remembers of a token (it never keeps the token itself)."""

    display_id: int
    session_id: int
    attempt: int
    shown: bool = False


def _db_dt(at: datetime) -> str:
    return at.astimezone(UTC).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    return (dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)).astimezone(UTC)


def _from_row(row: sqlite3.Row) -> Display:
    created = _parse_dt(row["created_at"])
    assert created is not None
    return Display(
        id=row["id"],
        connection_id=row["connection_id"],
        session_id=row["session_id"],
        user=row["user"],
        kind=row["kind"],
        version=row["version"],
        created_at=created,
        attempts=row["attempts"],
        first_shown_at=_parse_dt(row["first_shown_at"]),
        last_shown_at=_parse_dt(row["last_shown_at"]),
        acknowledged_at=_parse_dt(row["acknowledged_at"]),
        ack_ms=row["ack_ms"],
        closed_reason=row["closed_reason"],
    )


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _account(user: str, domain: str | None) -> str:
    return f"{domain}\\{user}" if domain else user


class NoticeDisplays:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        log: LogSink,
        notice: NoticeStore,
        tracker: SessionTracker,
        tamper: TamperMonitor,
    ) -> None:
        self._db = db
        self._clock = clock
        self._log = log
        self._notice = notice
        self._tracker = tracker
        self._tamper = tamper
        self._issued: dict[str, _Issued] = {}  # sha256(token) -> issued ticket
        self._digest_of: dict[int, str] = {}  # display id -> its current token's sha256
        self._listeners: list[Callable[[DisplayEvent, Display], None]] = []

    # --- lifecycle -------------------------------------------------------------------------

    def start(self) -> int:
        """Close the displays a previous run left open (``service_restart``); returns the count."""
        closed = self._close_where("closed_reason IS NULL", (), "service_restart")
        return len(closed)

    def add_listener(self, fn: Callable[[DisplayEvent, Display], None]) -> None:
        self._listeners.append(fn)

    def on_session_change(self, change: Change) -> None:
        """Tracker listener: a new connection gets a display; a logoff closes the open one.

        A disconnect leaves the display open; the reconnect's ``Opened`` supersedes it."""
        if isinstance(change, Opened):
            self.create(change.connection)
        elif isinstance(change, Closed) and change.reason == "logoff":
            self.close_pending(change.session_id, "logoff")

    # --- displays --------------------------------------------------------------------------

    def create(self, conn: Connection) -> Display:
        """A new display for ``conn`` with the current notice version; any open display of the
        same session is closed as ``superseded``."""
        now = self._clock.now()
        version = self._notice.current().version
        with self._db.transaction() as tx:
            rows = tx.execute(
                f"SELECT {_COLUMNS} FROM notice_displays WHERE session_id = ? AND closed_reason IS NULL",
                (conn.session_id,),
            ).fetchall()
            tx.execute(
                "UPDATE notice_displays SET closed_reason = 'superseded'"
                " WHERE session_id = ? AND closed_reason IS NULL",
                (conn.session_id,),
            )
            cur = tx.execute(
                "INSERT INTO notice_displays (connection_id, session_id, user, kind, version, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (conn.id, conn.session_id, _account(conn.user, conn.domain), conn.kind, version,
                 _db_dt(now)),
            )
            new_id = cur.lastrowid
        self._forget_session(conn.session_id)
        for row in rows:
            self._log_unacknowledged(_from_row(row), "superseded")
        display = self.get(new_id) if new_id is not None else None
        assert display is not None
        self._tracker.set_notice_state(conn.id, False)
        self._notify("created", display)
        return display

    def get(self, display_id: int) -> Display | None:
        rows = self._db.query(f"SELECT {_COLUMNS} FROM notice_displays WHERE id = ?", (display_id,))
        return _from_row(rows[0]) if rows else None

    def pending_for_session(self, session_id: int) -> Display | None:
        rows = self._db.query(
            f"SELECT {_COLUMNS} FROM notice_displays WHERE session_id = ? AND closed_reason IS NULL"
            " ORDER BY id DESC LIMIT 1",
            (session_id,),
        )
        return _from_row(rows[0]) if rows else None

    def latest_for_connections(self, ids: Iterable[int]) -> dict[int, Display]:
        """The newest display of each connection that has one."""
        wanted = list(dict.fromkeys(ids))
        out: dict[int, Display] = {}
        for i in range(0, len(wanted), _IN_CHUNK):
            chunk = wanted[i : i + _IN_CHUNK]
            marks = ", ".join("?" * len(chunk))
            rows = self._db.query(
                f"SELECT {_COLUMNS} FROM notice_displays WHERE id IN ("
                f" SELECT MAX(id) FROM notice_displays WHERE connection_id IN ({marks})"
                " GROUP BY connection_id)",
                chunk,
            )
            for row in rows:
                d = _from_row(row)
                out[d.connection_id] = d
        return out

    def close_pending(self, session_id: int, reason: Literal["logoff"]) -> None:
        self._close_where("session_id = ? AND closed_reason IS NULL", (session_id,), reason)
        self._forget_session(session_id)

    def unacknowledged(
        self, display_id: int, reason: Literal["agent_exited", "window_closed"]
    ) -> None:
        """Record that an open display went unconfirmed this time; it stays open (shown again)."""
        d = self.get(display_id)
        if d is not None and d.closed_reason is None:
            self._log_unacknowledged(d, reason)

    # --- tokens ----------------------------------------------------------------------------

    def issue(self, display_id: int) -> Ticket:
        """A fresh token for the next showing of an open display (the previous one stops working)."""
        with self._db.transaction() as tx:
            row = tx.execute(
                "UPDATE notice_displays SET attempts = attempts + 1"
                " WHERE id = ? AND closed_reason IS NULL RETURNING session_id, attempts",
                (display_id,),
            ).fetchone()
        if row is None:
            raise DisplayNotFoundError(display_id)
        token = secrets.token_urlsafe(32)
        digest = _digest(token)
        old = self._digest_of.pop(display_id, None)
        if old is not None:
            self._issued.pop(old, None)
        self._issued[digest] = _Issued(display_id, row["session_id"], row["attempts"])
        self._digest_of[display_id] = digest
        return Ticket(display_id, token, row["attempts"])

    def knows(self, token: str) -> bool:
        """Whether ``token`` is a live token: cheap, checked before the peer scan (M1)."""
        return bool(token) and _digest(token) in self._issued

    def open(self, token: str, peer_session: int | None) -> tuple[Display, NoticeContent]:
        """The page reports it is showing: log ``notice_shown`` once per attempt; returns the
        display and its pinned notice text."""
        display, issued = self._check(token, peer_session, ack=False)
        pinned = self._notice.version(display.version)
        if pinned is None:  # versions are append-only, so this cannot happen
            raise DisplayNotFoundError(display.id)
        if not issued.shown:
            issued.shown = True
            now = _db_dt(self._clock.now())
            self._db.execute(
                "UPDATE notice_displays SET first_shown_at = COALESCE(first_shown_at, ?),"
                " last_shown_at = ? WHERE id = ?",
                (now, now, display.id),
            )
            display = self._require(display.id)
            self._log.emit("notice", event="notice_shown", **self._fields(display, issued.attempt))
        return display, pinned.content

    def acknowledge(self, token: str, peer_session: int | None) -> Display:
        """The user confirmed: close the display as ``acknowledged`` (idempotent per token)."""
        display, issued = self._check(token, peer_session, ack=True)
        if display.closed_reason == "acknowledged":
            return display
        now = self._clock.now()
        last = display.last_shown_at or now
        ack_ms = round((now - last).total_seconds() * 1000)
        changed = self._db.execute_rowcount(
            "UPDATE notice_displays SET acknowledged_at = ?, ack_ms = ?, closed_reason = 'acknowledged'"
            " WHERE id = ? AND closed_reason IS NULL",
            (_db_dt(now), ack_ms, display.id),
        )
        display = self._require(display.id)
        if not changed:  # closed between the check and the update: not ours to acknowledge
            raise DisplayNotFoundError(display.id)
        self._log.emit(
            "notice", event="notice_acknowledged", **self._fields(display, issued.attempt),
            elapsed_ms=ack_ms,
        )
        self._tracker.set_notice_state(display.connection_id, True)
        self._notify("acknowledged", display)
        return display

    def _check(self, token: str, peer_session: int | None, *, ack: bool) -> tuple[Display, _Issued]:
        issued = self._issued.get(_digest(token))
        if issued is None:
            raise DisplayNotFoundError("unknown token")
        display = self.get(issued.display_id)
        if display is None:
            raise DisplayNotFoundError(issued.display_id)
        reopen_ok = ack and display.closed_reason == "acknowledged"
        if display.closed_reason is not None and not reopen_ok:
            raise DisplayNotFoundError(display.id)
        if peer_session is None:  # unresolved peer: no evidence of misuse (M2)
            raise DisplayNotFoundError(display.id)
        if peer_session != display.session_id:
            self._tamper.report_throttled(  # M3: once per display and peer session per minute
                "notice_token_misuse", key=(display.id, peer_session), window_sec=MISUSE_REPORT_SEC,
                display_id=display.id, session_id=display.session_id, peer_session=peer_session,
            )
            raise DisplayNotFoundError(display.id)
        return display, issued

    # --- helpers ---------------------------------------------------------------------------

    def _require(self, display_id: int) -> Display:
        d = self.get(display_id)
        if d is None:
            raise DisplayNotFoundError(display_id)
        return d

    def _close_where(self, where: str, params: tuple[Any, ...], reason: CloseReason) -> list[Display]:
        with self._db.transaction() as tx:
            rows = tx.execute(
                f"SELECT {_COLUMNS} FROM notice_displays WHERE {where} ORDER BY id", params
            ).fetchall()
            tx.execute(f"UPDATE notice_displays SET closed_reason = ? WHERE {where}", (reason, *params))
        closed = [_from_row(r) for r in rows]
        for d in closed:
            self._log_unacknowledged(d, reason)
        return closed

    def _forget_session(self, session_id: int) -> None:
        """Drop the tokens of a session's earlier displays (keeps the token map bounded)."""
        for digest, issued in list(self._issued.items()):
            if issued.session_id == session_id:
                del self._issued[digest]
                self._digest_of.pop(issued.display_id, None)

    @staticmethod
    def _fields(d: Display, attempt: int) -> dict[str, Any]:
        return {
            "display_id": d.id,
            "connection_id": d.connection_id,
            "session_id": d.session_id,
            "user": d.user,
            "kind": d.kind,
            "version": d.version,
            "attempt": attempt,
        }

    def _log_unacknowledged(self, d: Display, reason: str) -> None:
        self._log.emit(
            "notice", event="notice_unacknowledged", **self._fields(d, d.attempts), reason=reason
        )

    def _notify(self, what: DisplayEvent, display: Display) -> None:
        for fn in list(self._listeners):
            fn(what, display)
