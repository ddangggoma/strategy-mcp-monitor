from datetime import datetime, timezone

import pytest

from app.clock import to_kst_iso

def test_kst_iso():
    dt = datetime(2026, 11, 4, 15, 0, 0, 5000, tzinfo=timezone.utc)
    assert to_kst_iso(dt) == "2026-11-05T00:00:00.005+09:00"

def test_migrate_creates_tables(db):
    names = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"settings", "users", "otp_codes", "otp_ip_requests", "auth_sessions", "secrets"} <= names
    assert db.query("PRAGMA journal_mode")[0][0] == "wal"

def test_migrate_idempotent(db):
    db.migrate()
    assert db.query("PRAGMA user_version")[0][0] == 1

def test_transaction_rollback(db):
    try:
        with db.transaction() as conn:
            conn.execute("INSERT INTO secrets(name, value) VALUES ('x', 'y')")
            raise RuntimeError
    except RuntimeError:
        pass
    assert db.query("SELECT * FROM secrets WHERE name='x'") == []


def test_transaction_commit_persists(db):
    with db.transaction() as conn:
        conn.execute("INSERT INTO secrets(name, value) VALUES ('k', 'v')")
    assert [r["value"] for r in db.query("SELECT value FROM secrets WHERE name='k'")] == ["v"]


def test_transaction_is_immediate(db, paths):
    import sqlite3

    other = sqlite3.connect(str(paths.db_path), timeout=0, isolation_level=None)
    try:
        with db.transaction():
            with pytest.raises(sqlite3.OperationalError):
                other.execute("BEGIN IMMEDIATE")
    finally:
        other.close()


def test_transaction_serializes_threads(db):
    import threading
    import time

    entered = threading.Event()
    release = threading.Event()
    done_b = threading.Event()

    def thread_a():
        with db.transaction() as conn:
            conn.execute("INSERT INTO secrets(name, value) VALUES ('a', '1')")
            entered.set()
            release.wait(5)

    def thread_b():
        db.execute("INSERT INTO secrets(name, value) VALUES ('b', '2')")
        done_b.set()

    ta = threading.Thread(target=thread_a)
    ta.start()
    assert entered.wait(5)
    tb = threading.Thread(target=thread_b)
    tb.start()
    time.sleep(0.2)
    assert not done_b.is_set()
    release.set()
    ta.join(5)
    tb.join(5)
    assert done_b.is_set()
    assert {r["name"] for r in db.query("SELECT name FROM secrets")} == {"a", "b"}


def test_failed_commit_does_not_wedge(db):
    import sqlite3

    db.execute("CREATE TABLE parent_t(id INTEGER PRIMARY KEY)")
    db.execute(
        "CREATE TABLE child_t(id INTEGER PRIMARY KEY, "
        "pid INTEGER REFERENCES parent_t(id) DEFERRABLE INITIALLY DEFERRED)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute("INSERT INTO child_t(pid) VALUES (999)")
    with db.transaction() as conn:
        conn.execute("INSERT INTO secrets(name, value) VALUES ('after', 'ok')")
    assert db.query("SELECT * FROM child_t") == []
    assert len(db.query("SELECT * FROM secrets WHERE name='after'")) == 1
