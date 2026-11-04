import sqlite3
from datetime import UTC, datetime

import pytest

from app.clock import to_kst_iso
from app.db import MIGRATIONS


def test_kst_iso():
    dt = datetime(2026, 11, 4, 15, 0, 0, 5000, tzinfo=UTC)
    assert to_kst_iso(dt) == "2026-11-05T00:00:00.005+09:00"

def test_migrate_creates_tables(db):
    names = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"settings", "users", "otp_codes", "otp_ip_requests", "auth_sessions", "secrets"} <= names
    assert {"mcps", "mcp_scripts", "mcp_script_versions", "mcp_minutes", "mcp_transitions", "mcp_actions"} <= names
    assert db.query("PRAGMA journal_mode")[0][0] == "wal"

def test_migrate_idempotent(db):
    db.migrate()
    assert db.query("PRAGMA user_version")[0][0] == len(MIGRATIONS)

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
        with db.transaction(), pytest.raises(sqlite3.OperationalError):
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
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
        conn.execute("INSERT INTO child_t(pid) VALUES (999)")
    with db.transaction() as conn:
        conn.execute("INSERT INTO secrets(name, value) VALUES ('after', 'ok')")
    assert db.query("SELECT * FROM child_t") == []
    assert len(db.query("SELECT * FROM secrets WHERE name='after'")) == 1


def test_migration_3_creates_verify_ip_table(db):
    names = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "otp_verify_ip" in names
    assert db.query("PRAGMA user_version")[0][0] >= 3


def test_split_statements_handles_semicolons_in_literals_and_triggers():
    from app.db import split_statements

    script = """
    CREATE TABLE t (a TEXT DEFAULT 'x;y');
    CREATE TRIGGER trg AFTER INSERT ON t BEGIN
        UPDATE t SET a = 'q;r' WHERE rowid = NEW.rowid;
        DELETE FROM t WHERE a = 'none';
    END;
    INSERT INTO t (a) VALUES ('a;b')
    """
    stmts = split_statements(script)
    assert len(stmts) == 3
    assert stmts[0].startswith("CREATE TABLE") and "'x;y'" in stmts[0]
    assert stmts[1].startswith("CREATE TRIGGER") and stmts[1].rstrip().endswith("END;")
    assert stmts[2].startswith("INSERT")


def test_migrate_runs_trigger_migration_atomically(db, monkeypatch):
    import app.db as dbmod

    trigger = (
        "CREATE TABLE tt (a TEXT);"
        " CREATE TRIGGER tg AFTER INSERT ON tt BEGIN UPDATE tt SET a = 'z;z'; END;"
    )
    orig = list(dbmod.MIGRATIONS)
    monkeypatch.setattr(dbmod, "MIGRATIONS", [*orig, trigger, "CREATE TABLE tt (a TEXT);"])
    with pytest.raises(sqlite3.OperationalError):
        db.migrate()  # the last one fails (tt exists) -> its own transaction rolls back
    assert db.query("PRAGMA user_version")[0][0] == len(orig) + 1


def test_transaction_reentry_raises(db):
    with db.transaction(), pytest.raises(RuntimeError, match="already open"), db.transaction():
        pass
    db.execute("INSERT INTO secrets(name, value) VALUES ('ok', '1')")
    assert len(db.query("SELECT * FROM secrets WHERE name='ok'")) == 1


def test_transaction_reentry_does_not_roll_back_outer(db):
    with db.transaction() as conn:
        conn.execute("INSERT INTO secrets(name, value) VALUES ('outer', '1')")
        with pytest.raises(RuntimeError), db.transaction():
            pass
    assert len(db.query("SELECT * FROM secrets WHERE name='outer'")) == 1


def test_execute_rowcount(db):
    db.execute("INSERT INTO secrets(name, value) VALUES ('a','1')")
    db.execute("INSERT INTO secrets(name, value) VALUES ('b','1')")
    assert db.execute_rowcount("UPDATE secrets SET value='2'") == 2
    assert db.execute_rowcount("DELETE FROM secrets WHERE name='zz'") == 0
