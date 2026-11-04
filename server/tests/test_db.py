from datetime import datetime, timezone
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
