from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1
    """
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('developer','admin')),
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        created_by INTEGER,
        last_login_at TEXT
    );
    CREATE TABLE otp_codes (
        email TEXT PRIMARY KEY,
        code_hash TEXT,
        expires_at TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_sent_at TEXT NOT NULL
    );
    CREATE TABLE otp_ip_requests (
        ip TEXT NOT NULL,
        at TEXT NOT NULL
    );
    CREATE TABLE auth_sessions (
        id_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        channel TEXT NOT NULL,
        csrf_token TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        ip TEXT,
        user_agent TEXT
    );
    CREATE TABLE secrets (
        name TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    # 2
    """
    CREATE TABLE otp_failures (
        email TEXT NOT NULL,
        at TEXT NOT NULL
    );
    CREATE INDEX idx_otp_failures_email ON otp_failures(email);
    """,
    # 3
    """
    CREATE TABLE otp_verify_ip (
        ip TEXT NOT NULL,
        at TEXT NOT NULL
    );
    CREATE INDEX idx_otp_verify_ip_ip ON otp_verify_ip(ip);
    """,
]


def split_statements(script: str) -> list[str]:
    """Split a migration script into complete SQL statements (safe for ';' inside literals/triggers)."""
    statements: list[str] = []
    buf = ""
    for piece in script.split(";"):
        buf += piece + ";"
        if sqlite3.complete_statement(buf):  # false inside a literal or an unfinished trigger body
            stmt = buf.strip()
            if stmt != ";":  # whitespace after the final ';'
                statements.append(stmt)
            buf = ""
    tail = buf[:-1].strip()  # incomplete remainder (the ';' appended above is not part of it)
    if tail:
        statements.append(tail)
    return statements


class Database:
    def __init__(self, path: Path) -> None:
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(path), check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def query(self, sql: str, params: Sequence = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def execute(self, sql: str, params: Sequence = ()) -> int:
        with self._lock:
            return self._conn.execute(sql, params).lastrowid

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE transaction on the shared connection.

        Invariants: call only from the event-loop thread (the RLock is thread-owned and
        the connection is shared), and never ``await`` inside the body - a suspended
        transaction would stay open while other tasks run on the same connection.
        """
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except BaseException:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise

    def migrate(self) -> None:
        with self._lock:
            current = self._conn.execute("PRAGMA user_version").fetchone()[0]
            for version, script in enumerate(MIGRATIONS[current:], start=current + 1):
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    for stmt in split_statements(script):
                        self._conn.execute(stmt)
                    self._conn.execute(f"PRAGMA user_version = {version}")
                    self._conn.execute("COMMIT")
                except BaseException:
                    if self._conn.in_transaction:
                        self._conn.execute("ROLLBACK")
                    raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()
