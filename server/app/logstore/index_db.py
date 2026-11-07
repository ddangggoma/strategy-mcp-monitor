"""The log search index ``data/index.db``: schema, the writer connection and read-only readers.

The index is derived data (ruling W2): it can always be rebuilt from the JSONL files, so a file with
another schema version (older or newer) is deleted and created again instead of migrated.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

INDEX_SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE files (
    name TEXT PRIMARY KEY,
    day TEXT NOT NULL,
    offset INTEGER NOT NULL DEFAULT 0,      -- uncompressed bytes consumed
    size INTEGER NOT NULL DEFAULT 0,        -- on-disk size at the last look
    lines INTEGER NOT NULL DEFAULT 0,
    bad_lines INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0         -- 1 = .gz read to the end (immutable)
);
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    ts_ms INTEGER NOT NULL,
    day TEXT NOT NULL,
    cat TEXT NOT NULL,
    event TEXT,
    user TEXT COLLATE NOCASE,
    session_id INTEGER,
    client_ip TEXT,
    outcome TEXT,
    line_hash BLOB NOT NULL,
    raw TEXT NOT NULL
);
CREATE UNIQUE INDEX ux_events_line ON events(day, line_hash);
CREATE INDEX ix_events_ts ON events(ts_ms);
CREATE INDEX ix_events_user ON events(user, ts_ms);
CREATE INDEX ix_events_cat ON events(cat, ts_ms);
CREATE INDEX ix_events_session ON events(session_id, ts_ms) WHERE session_id IS NOT NULL;
CREATE INDEX ix_events_ip ON events(client_ip, ts_ms) WHERE client_ip IS NOT NULL;
CREATE VIRTUAL TABLE events_fts USING fts5(search, content='', contentless_delete=1, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE counts_min (bucket INTEGER NOT NULL, cat TEXT NOT NULL, user TEXT NOT NULL COLLATE NOCASE, n INTEGER NOT NULL, PRIMARY KEY (bucket, cat, user)) WITHOUT ROWID;
CREATE TABLE counts_hour (bucket INTEGER NOT NULL, cat TEXT NOT NULL, user TEXT NOT NULL COLLATE NOCASE, n INTEGER NOT NULL, PRIMARY KEY (bucket, cat, user)) WITHOUT ROWID;
"""
# counts_min.bucket = ts_ms // 60000, counts_hour.bucket = ts_ms // 3600000; a None user is ''.


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    try:
        mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            raise RuntimeError(f"journal_mode is {mode}; WAL is required")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
    except BaseException:
        conn.close()
        raise
    return conn


def _remove(path: Path) -> None:
    for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        p.unlink(missing_ok=True)


def _create(path: Path) -> sqlite3.Connection:
    """Open ``path`` (an empty database) and apply the schema and its version in one transaction."""
    conn = _connect(path)
    try:
        conn.executescript(f"BEGIN IMMEDIATE;\n{SCHEMA}\nPRAGMA user_version = {INDEX_SCHEMA_VERSION};\nCOMMIT;")
    except BaseException:
        conn.close()
        raise
    return conn


def _version(path: Path) -> int | None:
    """The schema version of an empty-or-ours database, or None when it must be wiped: another
    layout at version 0, or a file SQLite cannot read as a database."""
    conn: sqlite3.Connection | None = None
    try:
        conn = _connect(path)
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version == 0 and conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]:
            return None
        return version
    except sqlite3.DatabaseError:  # "file is not a database", a damaged file: rebuilt from the JSONL
        return None
    finally:
        if conn is not None:
            conn.close()


def prepare_index(path: Path) -> tuple[sqlite3.Connection, bool]:
    """The writer connection to the index at ``path`` and whether it was (re)created empty.

    A new file gets the schema. A file with another schema version (older or newer), or one SQLite
    cannot read as a database, is deleted with its ``-wal``/``-shm`` and created again (W2).
    """
    path = Path(path)
    version = _version(path)
    if version == INDEX_SCHEMA_VERSION:
        return _connect(path), False
    if version != 0:
        _remove(path)
    return _create(path), True


def open_reader(path: Path) -> sqlite3.Connection:
    """A read-only connection to the index (one per reading thread)."""
    conn = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True, check_same_thread=False)
    try:
        conn.execute("PRAGMA query_only=1")
        conn.execute("PRAGMA cache_size=-16384")
        conn.execute("PRAGMA mmap_size=268435456")
        conn.execute("PRAGMA busy_timeout=5000")
    except BaseException:
        conn.close()
        raise
    conn.row_factory = sqlite3.Row
    return conn
