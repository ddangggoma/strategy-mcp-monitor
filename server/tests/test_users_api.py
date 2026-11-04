from tests.test_auth_api import audit_events, bootstrap, login


async def admin_client(local_client, services):
    await bootstrap(local_client); await login(local_client, services)
    return local_client


async def test_create_and_promote(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    r = await c.post("/api/users", json={"email": "Dev@x.com", "name": "개발자", "role": "developer"}, headers=h)
    assert r.status_code == 201 and r.json()["email"] == "dev@x.com"
    uid = r.json()["id"]
    assert (await c.patch(f"/api/users/{uid}", json={"role": "admin"}, headers=h)).json()["role"] == "admin"


async def test_duplicate_and_invalid(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    assert (await c.post("/api/users", json={"email": "ADMIN@x.com", "name": "a", "role": "developer"}, headers=h)).json() == {"error": "user_exists"}
    assert (await c.post("/api/users", json={"email": "nope", "name": "a", "role": "developer"}, headers=h)).status_code == 422


async def test_last_admin(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    me = (await c.get("/api/auth/me")).json()["user"]["id"]
    r = await c.patch(f"/api/users/{me}", json={"role": "developer"}, headers=h)
    assert r.status_code == 409 and r.json() == {"error": "last_admin"}


async def test_csrf_required(local_client, services):
    c = await admin_client(local_client, services)
    r = await c.post("/api/users", json={"email": "d@x.com", "name": "d", "role": "developer"})
    assert r.status_code == 403 and r.json() == {"error": "csrf"}


async def test_developer_forbidden(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    await c.post("/api/users", json={"email": "dev@x.com", "name": "d", "role": "developer"}, headers=h)
    await c.post("/api/auth/logout", headers=h)
    services.otp.provider.sent.clear(); services.clock.advance(61)
    await login(c, services, "dev@x.com")
    assert (await c.get("/api/users")).json() == {"error": "forbidden"}


async def test_anonymous_401(local_client):
    assert (await local_client.get("/api/users")).status_code == 401


async def test_users_api_absent_on_external(local_client, external_client, services):
    await bootstrap(local_client); await login(external_client, services)
    assert (await external_client.get("/api/users")).status_code == 404


async def test_deactivate_revokes_session(local_client, external_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    uid = (await c.post("/api/users", json={"email": "dev@x.com", "name": "d", "role": "developer"}, headers=h)).json()["id"]
    services.clock.advance(61); await login(external_client, services, "dev@x.com")
    assert (await external_client.get("/api/auth/me")).json()["user"] is not None
    await c.patch(f"/api/users/{uid}", json={"active": False}, headers=h)
    assert (await external_client.get("/api/auth/me")).json()["user"] is None


# --- additional coverage ---


async def test_list_users_shape(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    await c.post("/api/users", json={"email": "dev@x.com", "name": "d", "role": "developer"}, headers=h)
    rows = (await c.get("/api/users")).json()
    assert [u["email"] for u in rows] == ["admin@x.com", "dev@x.com"]
    admin, dev = rows
    assert set(admin) == {"id", "email", "name", "role", "active", "created_at", "last_login_at"}
    assert admin["last_login_at"] is not None and admin["last_login_at"].endswith("+09:00")
    assert dev["last_login_at"] is None and dev["created_at"].endswith("+09:00")
    assert dev["active"] is True and dev["role"] == "developer"


async def test_patch_unknown_user_404(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    r = await c.patch("/api/users/9999", json={"name": "x"}, headers=h)
    assert r.status_code == 404 and r.json() == {"error": "not_found"}


async def test_empty_name_422(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    r = await c.post("/api/users", json={"email": "d@x.com", "name": "  ", "role": "developer"}, headers=h)
    assert r.status_code == 422 and r.json() == {"error": "validation"}
    me = (await c.get("/api/auth/me")).json()["user"]["id"]
    r = await c.patch(f"/api/users/{me}", json={"name": " "}, headers=h)
    assert r.status_code == 422 and r.json() == {"error": "validation"}


async def test_bad_role_422(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    r = await c.post("/api/users", json={"email": "d@x.com", "name": "d", "role": "root"}, headers=h)
    assert r.status_code == 422 and r.json() == {"error": "validation"}


async def test_empty_patch_noop_not_audited(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    me = (await c.get("/api/auth/me")).json()["user"]["id"]
    r = await c.patch(f"/api/users/{me}", json={}, headers=h)
    assert r.status_code == 200 and r.json()["id"] == me
    assert [e for e in await audit_events(services, "admin.audit") if e["action"] == "user_update"] == []


async def test_unchanged_values_keep_sessions_and_no_audit(local_client, external_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    uid = (await c.post("/api/users", json={"email": "dev@x.com", "name": "d", "role": "developer"}, headers=h)).json()["id"]
    services.clock.advance(61); await login(external_client, services, "dev@x.com")
    r = await c.patch(f"/api/users/{uid}", json={"role": "developer", "active": True}, headers=h)
    assert r.status_code == 200
    assert (await external_client.get("/api/auth/me")).json()["user"] is not None
    assert [e for e in await audit_events(services, "admin.audit") if e["action"] == "user_update"] == []


async def test_name_change_keeps_session(local_client, external_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    uid = (await c.post("/api/users", json={"email": "dev@x.com", "name": "d", "role": "developer"}, headers=h)).json()["id"]
    services.clock.advance(61); await login(external_client, services, "dev@x.com")
    r = await c.patch(f"/api/users/{uid}", json={"name": "새 이름"}, headers=h)
    assert r.json()["name"] == "새 이름"
    assert (await external_client.get("/api/auth/me")).json()["user"] is not None


async def test_audit_records(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    r = await c.post("/api/users", json={"email": "dev@x.com", "name": "d", "role": "developer"}, headers=h)
    uid = r.json()["id"]
    await c.post("/api/users", json={"email": "dev@x.com", "name": "d", "role": "developer"}, headers=h)
    await c.patch(f"/api/users/{uid}", json={"role": "admin", "active": False}, headers=h)
    me = (await c.get("/api/auth/me")).json()["user"]["id"]
    # admin (me) + uid(admin, inactive): me is the last active admin
    await c.patch(f"/api/users/{me}", json={"role": "developer"}, headers=h)
    events = [e for e in await audit_events(services, "admin.audit") if e["action"].startswith("user_")]
    assert [(e["action"], e["result"]) for e in events] == [
        ("user_create", "ok"), ("user_create", "error"), ("user_update", "ok"), ("user_update", "error"),
    ]
    create, dup, upd, last = events
    assert create["actor_email"] == "admin@x.com" and create["channel"] == "local"
    assert create["target"]["user_id"] == uid and create["target"]["email"] == "dev@x.com"
    assert dup["target"]["error"] == "user_exists" and dup["target"]["email"] == "dev@x.com"
    assert upd["target"]["user_id"] == uid
    assert upd["target"]["changes"] == {"role": ["developer", "admin"], "active": [True, False]}
    assert last["target"]["error"] == "last_admin" and last["target"]["user_id"] == me


async def test_self_demotion_with_other_admin_revokes_own_session(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    r = await c.post("/api/users", json={"email": "b@x.com", "name": "b", "role": "admin"}, headers=h)
    assert r.status_code == 201
    me = (await c.get("/api/auth/me")).json()["user"]["id"]
    r = await c.patch(f"/api/users/{me}", json={"role": "developer"}, headers=h)
    assert r.status_code == 200 and r.json()["role"] == "developer"
    assert (await c.get("/api/auth/me")).json()["user"] is None


# --- request hardening ---


async def test_huge_user_id_422(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    for uid in (2**63, 10**30, 0, -1):
        r = await c.patch(f"/api/users/{uid}", json={"name": "x"}, headers=h)
        assert r.status_code == 422 and r.json() == {"error": "validation"}, uid
    r = await c.patch(f"/api/users/{2**63 - 1}", json={"name": "x"}, headers=h)
    assert r.status_code == 404


async def test_user_bodies_strict_422(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    me = (await c.get("/api/auth/me")).json()["user"]["id"]
    ok = {"email": "d@x.com", "name": "d", "role": "developer"}
    bad_create = [
        {**ok, "extra": 1},
        {**ok, "name": "n" * 101},
        {**ok, "email": "a" * 315 + "@x.com"},
    ]
    for body in bad_create:
        r = await c.post("/api/users", json=body, headers=h)
        assert r.status_code == 422 and r.json() == {"error": "validation"}, body
    bad_patch = [{"active": "yes"}, {"active": 1}, {"nope": 1}, {"name": "n" * 101}]
    for body in bad_patch:
        r = await c.patch(f"/api/users/{me}", json=body, headers=h)
        assert r.status_code == 422 and r.json() == {"error": "validation"}, body
    # boundary values are accepted
    r = await c.post("/api/users", json={**ok, "name": "n" * 100}, headers=h)
    assert r.status_code == 201
