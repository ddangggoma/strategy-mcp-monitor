import pytest

from app.auth.sessions import SESSION_ABSOLUTE_SEC, SESSION_IDLE_SEC, SessionStore
from app.users.store import UserStore


def setup(db, clock):
    uid = UserStore(db, clock).create("a@x.com", "a", "admin", None).id
    return SessionStore(db, clock), uid


def test_idle_timeout(db, clock):
    s, uid = setup(db, clock); sid, _ = s.create(uid, "local", "127.0.0.1", "ua")
    clock.advance(29 * 60); assert s.get(sid, "local") is not None
    clock.advance(29 * 60); assert s.get(sid, "local") is not None  # 활동으로 연장
    clock.advance(31 * 60); assert s.get(sid, "local") is None


def test_absolute_timeout(db, clock):
    s, uid = setup(db, clock); sid, _ = s.create(uid, "local", "ip", "ua")
    for _ in range(16): clock.advance(29 * 60); s.get(sid, "local")  # 7h44m
    clock.advance(20 * 60); assert s.get(sid, "local") is None          # 8h04m


def test_channel_bound(db, clock):
    s, uid = setup(db, clock); sid, _ = s.create(uid, "external", "ip", "ua")
    assert s.get(sid, "local") is None and s.get(sid, "external") is not None


def test_revoke_user(db, clock):
    s, uid = setup(db, clock); a, _ = s.create(uid, "local", "ip", "ua"); b, _ = s.create(uid, "external", "ip", "ua")
    s.revoke_user(uid)
    assert s.get(a, "local") is None and s.get(b, "external") is None


def test_id_stored_hashed(db, clock):
    s, uid = setup(db, clock); sid, _ = s.create(uid, "local", "ip", "ua")
    assert db.query("SELECT 1 FROM auth_sessions WHERE id_hash = ?", (sid,)) == []


def test_constants():
    assert SESSION_ABSOLUTE_SEC == 28800 and SESSION_IDLE_SEC == 1800


@pytest.mark.parametrize(
    "garbage", ["", "nope", "한글세션", "\ud800", "a\x00b", "x" * 100_000]
)
def test_garbage_session_id_returns_none(db, clock, garbage):
    s, uid = setup(db, clock); s.create(uid, "local", "ip", "ua")
    assert s.get(garbage, "local") is None


def test_get_returns_session_fields(db, clock):
    s, uid = setup(db, clock); sid, csrf = s.create(uid, "local", "ip", "ua")
    created = clock.now()
    clock.advance(60)
    got = s.get(sid, "local")
    assert got.user_id == uid and got.channel == "local" and got.csrf_token == csrf
    assert got.created_at == created and got.last_seen_at == clock.now()


def test_idle_boundary_is_expired(db, clock):
    s, uid = setup(db, clock); sid, _ = s.create(uid, "local", "ip", "ua")
    clock.advance(SESSION_IDLE_SEC - 1); assert s.get(sid, "local") is not None
    clock.advance(SESSION_IDLE_SEC); assert s.get(sid, "local") is None


def test_absolute_boundary_is_expired(db, clock):
    s, uid = setup(db, clock); sid, _ = s.create(uid, "local", "ip", "ua")
    # keep the session active up to 1s before the absolute limit
    for _ in range(SESSION_ABSOLUTE_SEC // 1500):
        clock.advance(1500); assert s.get(sid, "local") is not None
    clock.advance(SESSION_ABSOLUTE_SEC - (SESSION_ABSOLUTE_SEC // 1500) * 1500 - 1)
    assert s.get(sid, "local") is not None
    clock.advance(1)  # exactly 8h
    assert s.get(sid, "local") is None


def test_expired_row_deleted_on_get(db, clock):
    s, uid = setup(db, clock); sid, _ = s.create(uid, "local", "ip", "ua")
    clock.advance(SESSION_IDLE_SEC)
    assert s.get(sid, "local") is None
    assert db.query("SELECT 1 FROM auth_sessions") == []


def test_channel_mismatch_does_not_delete_or_touch(db, clock):
    s, uid = setup(db, clock); sid, _ = s.create(uid, "external", "ip", "ua")
    clock.advance(60)
    assert s.get(sid, "local") is None
    row = db.query("SELECT created_at, last_seen_at FROM auth_sessions")[0]
    assert row["created_at"] == row["last_seen_at"] or row["last_seen_at"] < clock.now().isoformat()
    assert s.get(sid, "external") is not None


def test_revoke_single(db, clock):
    s, uid = setup(db, clock)
    a, _ = s.create(uid, "local", "ip", "ua"); b, _ = s.create(uid, "local", "ip", "ua")
    s.revoke(a); s.revoke("garbage-\ud800")  # unknown/garbage revoke is a no-op
    assert s.get(a, "local") is None and s.get(b, "local") is not None


def test_ids_and_csrf_unique_and_stored_utc(db, clock):
    s, uid = setup(db, clock)
    a, ca = s.create(uid, "local", "ip", "ua"); b, cb = s.create(uid, "local", "ip", "ua")
    assert a != b and ca != cb and a != ca
    assert db.query("SELECT created_at FROM auth_sessions")[0]["created_at"].endswith("+00:00")


def test_create_unknown_user_raises(db, clock):
    import sqlite3
    s, _ = setup(db, clock)
    with pytest.raises(sqlite3.IntegrityError):
        s.create(9999, "local", "ip", "ua")
