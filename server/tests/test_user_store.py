import threading
from datetime import timedelta

import pytest

from app.users.store import (
    InvalidEmailError,
    LastAdminError,
    UserExistsError,
    UserNotFoundError,
    UserStore,
)


def test_email_normalized(db, clock):
    s = UserStore(db, clock)
    u = s.create("  Hong@Corp.COM ", "홍길동", "developer", None)
    assert u.email == "hong@corp.com"
    assert s.get_by_email("HONG@corp.com ").id == u.id

@pytest.mark.parametrize("bad", ["", "hong", "a@b", "a b@c.com", "a@@c.com", "a\ud800@x.com"])
def test_invalid_email(db, clock, bad):
    with pytest.raises(InvalidEmailError):
        UserStore(db, clock).create(bad, "x", "developer", None)

def test_duplicate(db, clock):
    s = UserStore(db, clock); s.create("a@x.com", "a", "admin", None)
    with pytest.raises(UserExistsError):
        s.create("A@X.com", "a2", "developer", None)

def test_last_admin_protected(db, clock):
    s = UserStore(db, clock); a = s.create("a@x.com", "a", "admin", None)
    with pytest.raises(LastAdminError): s.set_role(a.id, "developer")
    with pytest.raises(LastAdminError): s.set_active(a.id, False)
    b = s.create("b@x.com", "b", "admin", a.id)
    assert s.set_role(a.id, "developer").role == "developer"
    with pytest.raises(LastAdminError): s.set_active(b.id, False)

def test_inactive_admin_not_counted(db, clock):
    s = UserStore(db, clock); a = s.create("a@x.com", "a", "admin", None)
    b = s.create("b@x.com", "b", "admin", a.id); s.set_active(b.id, False)
    with pytest.raises(LastAdminError): s.set_role(a.id, "developer")

def test_concurrent_demotion_keeps_one_admin(db, clock):
    s = UserStore(db, clock); a = s.create("a@x.com", "a", "admin", None); b = s.create("b@x.com", "b", "admin", a.id)
    barrier = threading.Barrier(2); errors = []
    def demote(uid):
        barrier.wait()
        try: s.set_role(uid, "developer")
        except LastAdminError as e: errors.append(e)
    ts = [threading.Thread(target=demote, args=(u,)) for u in (a.id, b.id)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(errors) == 1
    assert sum(u.role == "admin" and u.active for u in s.list()) == 1


def test_developer_deactivate_and_reactivate_not_blocked(db, clock):
    s = UserStore(db, clock); s.create("a@x.com", "a", "admin", None)
    d = s.create("d@x.com", "d", "developer", None)
    assert s.set_active(d.id, False).active is False
    assert s.set_active(d.id, True).active is True


def test_inactive_admin_demotion_and_repromotion(db, clock):
    s = UserStore(db, clock); a = s.create("a@x.com", "a", "admin", None)
    b = s.create("b@x.com", "b", "admin", a.id); s.set_active(b.id, False)
    assert s.set_role(b.id, "developer").role == "developer"
    assert s.set_role(b.id, "admin").role == "admin"
    assert s.set_active(b.id, True).active is True
    d = s.create("d@x.com", "d", "developer", a.id)
    assert s.set_role(d.id, "admin").role == "admin"


def test_missing_user_raises_not_found(db, clock):
    s = UserStore(db, clock)
    with pytest.raises(UserNotFoundError): s.set_role(999, "admin")
    with pytest.raises(UserNotFoundError): s.set_active(999, False)
    with pytest.raises(UserNotFoundError): s.set_name(999, "x")


def test_invalid_role_and_empty_name(db, clock):
    s = UserStore(db, clock); a = s.create("a@x.com", "a", "admin", None)
    with pytest.raises(ValueError): s.create("b@x.com", "b", "root", None)
    with pytest.raises(ValueError): s.set_role(a.id, "root")
    with pytest.raises(ValueError): s.create("c@x.com", "   ", "developer", None)
    with pytest.raises(ValueError): s.set_name(a.id, "   ")
    assert s.set_name(a.id, "  new  ").name == "new"
    assert s.count() == 1


def test_get_by_email_invalid_returns_none(db, clock):
    s = UserStore(db, clock)
    assert s.get_by_email("not-an-email") is None
    assert s.get_by_email("") is None
    assert s.get_by_email("a\ud800@x.com") is None
    assert s.get_by_email("nobody@x.com") is None


def test_touch_login_count_and_utc_roundtrip(db, clock):
    s = UserStore(db, clock)
    assert s.count() == 0
    u = s.create("a@x.com", "a", "admin", None)
    s.create("b@x.com", "b", "developer", u.id)
    assert s.count() == 2
    assert u.last_login_at is None
    assert u.created_at == clock.now() and u.created_at.utcoffset() == timedelta(0)
    s.touch_login(u.id)
    got = s.get(u.id)
    assert got.last_login_at == clock.now()
    assert got.last_login_at.utcoffset() == timedelta(0)
    assert got.created_at.tzinfo is not None


def test_create_first_admin_only_when_empty(db, clock):
    from app.users.store import BootstrapDoneError

    s = UserStore(db, clock)
    user = s.create_first_admin(" Root@X.com ", " Root ")
    assert (user.email, user.name, user.role, user.active, user.created_by) == (
        "root@x.com", "Root", "admin", True, None
    )
    with pytest.raises(BootstrapDoneError):
        s.create_first_admin("other@x.com", "o")
    assert s.count() == 1
