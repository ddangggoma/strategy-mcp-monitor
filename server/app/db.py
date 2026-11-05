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
    # 4
    """
    CREATE TABLE mcps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        host TEXT NOT NULL,
        port INTEGER NOT NULL,
        config TEXT NOT NULL,                       -- McpConfig JSON (name/host/port included, always equal to the columns above)
        owner_id INTEGER REFERENCES users(id),
        created_by INTEGER REFERENCES users(id),
        created_at TEXT NOT NULL,
        UNIQUE (host, port)
    );
    CREATE TABLE mcp_scripts (
        mcp_id INTEGER NOT NULL REFERENCES mcps(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK (kind IN ('start','stop','restart')),
        ext TEXT NOT NULL CHECK (ext IN ('.ps1','.bat','.cmd')),
        sha256 TEXT NOT NULL,
        version INTEGER NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by INTEGER,
        PRIMARY KEY (mcp_id, kind)
    );
    CREATE TABLE mcp_script_versions (
        mcp_id INTEGER NOT NULL REFERENCES mcps(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        version INTEGER NOT NULL,
        ext TEXT,                                   -- ext/content/sha256 all NULL = deletion marker
        content TEXT,
        sha256 TEXT,
        author_id INTEGER,
        created_at TEXT NOT NULL,
        PRIMARY KEY (mcp_id, kind, version)
    );
    CREATE TABLE mcp_minutes (
        mcp_id INTEGER NOT NULL REFERENCES mcps(id) ON DELETE CASCADE,
        minute TEXT NOT NULL,
        ok INTEGER NOT NULL,
        total INTEGER NOT NULL,
        latency_sum REAL NOT NULL DEFAULT 0,
        latency_n INTEGER NOT NULL DEFAULT 0,
        latency_max REAL,
        PRIMARY KEY (mcp_id, minute)
    ) WITHOUT ROWID;
    CREATE TABLE mcp_transitions (
        id INTEGER PRIMARY KEY,
        mcp_id INTEGER NOT NULL REFERENCES mcps(id) ON DELETE CASCADE,
        at TEXT NOT NULL,
        from_state TEXT NOT NULL,
        to_state TEXT NOT NULL,
        issue TEXT
    );
    CREATE INDEX idx_mcp_transitions ON mcp_transitions(mcp_id, at);
    CREATE TABLE mcp_actions (
        id INTEGER PRIMARY KEY,
        run_id TEXT NOT NULL,
        mcp_id INTEGER NOT NULL REFERENCES mcps(id) ON DELETE CASCADE,
        at TEXT NOT NULL,
        requested TEXT NOT NULL,
        kind TEXT NOT NULL,
        trigger TEXT NOT NULL CHECK (trigger IN ('auto','manual','boot')),
        reason TEXT NOT NULL,
        actor_id INTEGER,
        status TEXT NOT NULL CHECK (status IN ('ok','failed','timeout','error')),
        exit_code INTEGER,
        duration_ms INTEGER NOT NULL,
        killed INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        stdout TEXT NOT NULL DEFAULT '',
        stderr TEXT NOT NULL DEFAULT '',
        stdout_truncated INTEGER NOT NULL DEFAULT 0,
        stderr_truncated INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_mcp_actions ON mcp_actions(mcp_id, at);
    """,
    # 5
    """
    CREATE TABLE notice_versions (
        version INTEGER PRIMARY KEY CHECK (version >= 1),   -- version 0 is the built-in text, never stored
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        button_text TEXT NOT NULL,
        author_id INTEGER,
        created_at TEXT NOT NULL,
        reverted_from INTEGER                               -- source version of a revert (0 = built-in text)
    );
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
        """Run one statement and return ``lastrowid``.

        The returned value is only meaningful for INSERT; use ``execute_rowcount`` to
        learn how many rows an UPDATE or DELETE touched.
        """
        with self._lock:
            # 0 when no row was inserted (sqlite3 reports None for some statements)
            return self._conn.execute(sql, params).lastrowid or 0

    def execute_rowcount(self, sql: str, params: Sequence = ()) -> int:
        """Run one statement and return the number of rows it changed."""
        with self._lock:
            return self._conn.execute(sql, params).rowcount

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE transaction on the shared connection.

        Invariants: call only from the event-loop thread (the RLock is thread-owned and
        the connection is shared), and never ``await`` inside the body - a suspended
        transaction would stay open while other tasks run on the same connection.
        """
        with self._lock:
            if self._conn.in_transaction:  # raise before the try: it must not roll back the outer one
                raise RuntimeError("transaction already open")
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
