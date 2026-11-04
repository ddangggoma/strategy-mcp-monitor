import threading, pytest
from app.users.store import UserStore, InvalidEmailError, UserExistsError, LastAdminError

def test_email_normalized(db, clock):
    s = UserStore(db, clock)
    u = s.create("  Hong@Corp.COM ", "홍길동", "developer", None)
    assert u.email == "hong@corp.com"
    assert s.get_by_email("HONG@corp.com ").id == u.id

@pytest.mark.parametrize("bad", ["", "hong", "a@b", "a b@c.com", "a@@c.com"])
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
