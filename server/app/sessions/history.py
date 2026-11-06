"""RDP connection history (``rdp_connections``) and RDP logon failures (``rdp_logon_failures``).

Call from the event-loop thread only (``Database.transaction`` rule).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from app.clock import Clock
from app.db import Database
from app.win.wts import WtsSession

CONNECTION_KINDS = ("logon", "reconnect", "existing")
END_REASONS = ("disconnect", "logoff", "reconnected", "service_stop")


def _db_dt(at: datetime) -> str:
    return at.astimezone(UTC).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass(frozen=True)
class Connection:
    id: int
    session_id: int
    logon_at: datetime | None
    kind: str
    user: str
    domain: str | None
    client_name: str | None
    client_ip: str | None
    client_build: int | None
    protocol: str
    resolution: str | None
    reverse_dns: str | None
    first_seen_ip: bool
    first_seen_device: bool
    connected_at: datetime
    ended_at: datetime | None
    end_reason: str | None


@dataclass(frozen=True)
class LogonFailureIn:
    at: datetime
    user: str | None
    domain: str | None
    client_ip: str | None
    workstation: str | None
    logon_type: int | None
    status: str | None
    sub_status: str | None
    source: str
    record_id: int | None


@dataclass(frozen=True)
class LogonFailure:
    id: int
    at: datetime
    user: str | None
    domain: str | None
    client_ip: str | None
    workstation: str | None
    logon_type: int | None
    status: str | None
    sub_status: str | None
    source: str
    record_id: int | None


def _connection(row: sqlite3.Row) -> Connection:
    connected_at = _parse_dt(row["connected_at"])
    assert connected_at is not None  # NOT NULL column
    return Connection(
        id=row["id"],
        session_id=row["session_id"],
        logon_at=_parse_dt(row["logon_at"]),
        kind=row["kind"],
        user=row["user"],
        domain=row["domain"],
        client_name=row["client_name"],
        client_ip=row["client_ip"],
        client_build=row["client_build"],
        protocol=row["protocol"],
        resolution=row["resolution"],
        reverse_dns=row["reverse_dns"],
        first_seen_ip=bool(row["first_seen_ip"]),
        first_seen_device=bool(row["first_seen_device"]),
        connected_at=connected_at,
        ended_at=_parse_dt(row["ended_at"]),
        end_reason=row["end_reason"],
    )


def _failure(row: sqlite3.Row) -> LogonFailure:
    at = _parse_dt(row["at"])
    assert at is not None  # NOT NULL column
    return LogonFailure(
        id=row["id"],
        at=at,
        user=row["user"],
        domain=row["domain"],
        client_ip=row["client_ip"],
        workstation=row["workstation"],
        logon_type=row["logon_type"],
        status=row["status"],
        sub_status=row["sub_status"],
        source=row["source"],
        record_id=row["record_id"],
    )


class SessionHistory:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def open(self, s: WtsSession, kind: str, at: datetime) -> Connection:
        """Insert an open connection row for ``s``.

        ``connected_at`` is the WTS connect time, or ``at`` (the snapshot time) when WTS has none.
        ``first_seen_ip``/``first_seen_device`` are true when no earlier row has that IP / that
        client name (case-insensitive).
        """
        if kind not in CONNECTION_KINDS:
            raise ValueError(f"unknown connection kind {kind!r}")
        connected_at = s.connected_at if s.connected_at is not None else at
        with self._db.transaction() as conn:
            first_ip = s.client_ip is not None and conn.execute(
                "SELECT 1 FROM rdp_connections WHERE client_ip = ? LIMIT 1", (s.client_ip,)
            ).fetchone() is None
            first_device = s.client_name is not None and conn.execute(
                "SELECT 1 FROM rdp_connections WHERE client_name = ? COLLATE NOCASE LIMIT 1",
                (s.client_name,),
            ).fetchone() is None
            cur = conn.execute(
                "INSERT INTO rdp_connections (session_id, logon_at, kind, user, domain, client_name,"
                " client_ip, client_build, protocol, resolution, first_seen_ip, first_seen_device,"
                " connected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    s.session_id,
                    _db_dt(s.logon_at) if s.logon_at is not None else None,
                    kind,
                    s.user,
                    s.domain,
                    s.client_name,
                    s.client_ip,
                    s.client_build,
                    s.protocol,
                    s.resolution,
                    int(first_ip),
                    int(first_device),
                    _db_dt(connected_at),
                ),
            )
            conn_id = cur.lastrowid
            assert conn_id is not None
        return Connection(
            id=conn_id,
            session_id=s.session_id,
            logon_at=s.logon_at.astimezone(UTC) if s.logon_at is not None else None,
            kind=kind,
            user=s.user,
            domain=s.domain,
            client_name=s.client_name,
            client_ip=s.client_ip,
            client_build=s.client_build,
            protocol=s.protocol,
            resolution=s.resolution,
            reverse_dns=None,
            first_seen_ip=first_ip,
            first_seen_device=first_device,
            connected_at=connected_at.astimezone(UTC),
            ended_at=None,
            end_reason=None,
        )

    def close(self, conn_id: int, at: datetime, reason: str) -> None:
        """End a connection; a row that already ended is left as it is."""
        if reason not in END_REASONS:
            raise ValueError(f"unknown end reason {reason!r}")
        self._db.execute(
            "UPDATE rdp_connections SET ended_at = ?, end_reason = ? WHERE id = ? AND ended_at IS NULL",
            (_db_dt(at), reason, conn_id),
        )

    def set_reverse_dns(self, conn_id: int, name: str | None) -> None:
        self._db.execute("UPDATE rdp_connections SET reverse_dns = ? WHERE id = ?", (name, conn_id))

    def close_dangling(self, at: datetime) -> int:
        """End every connection left open by a previous run (``service_stop``); returns the count."""
        return self._db.execute_rowcount(
            "UPDATE rdp_connections SET ended_at = ?, end_reason = 'service_stop' WHERE ended_at IS NULL",
            (_db_dt(at),),
        )

    def get(self, conn_id: int) -> Connection | None:
        rows = self._db.query("SELECT * FROM rdp_connections WHERE id = ?", (conn_id,))
        return _connection(rows[0]) if rows else None

    def connections(
        self, since: datetime, limit: int = 200, before_id: int | None = None
    ) -> list[Connection]:
        """Connections with ``connected_at >= since``, newest id first; ``before_id`` pages back."""
        sql = "SELECT * FROM rdp_connections WHERE connected_at >= ?"
        params: list[object] = [_db_dt(since)]
        if before_id is not None:
            sql += " AND id < ?"
            params.append(before_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [_connection(r) for r in self._db.query(sql, params)]

    def add_failure(self, f: LogonFailureIn) -> int | None:
        """Store a logon failure; ``None`` when ``(source, record_id)`` was already stored."""
        with self._db.transaction() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO rdp_logon_failures (at, user, domain, client_ip, workstation,"
                " logon_type, status, sub_status, source, record_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _db_dt(f.at), f.user, f.domain, f.client_ip, f.workstation, f.logon_type,
                    f.status, f.sub_status, f.source, f.record_id,
                ),
            )
            return cur.lastrowid if cur.rowcount == 1 else None

    def failures(self, since: datetime, limit: int = 200) -> list[LogonFailure]:
        """Logon failures with ``at >= since``, newest first."""
        rows = self._db.query(
            "SELECT * FROM rdp_logon_failures WHERE at >= ? ORDER BY at DESC, id DESC LIMIT ?",
            (_db_dt(since), limit),
        )
        return [_failure(r) for r in rows]
