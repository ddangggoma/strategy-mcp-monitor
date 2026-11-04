import json

import httpx

from app.web.app_factory import create_app


async def bootstrap(local_client):
    r = await local_client.post("/api/bootstrap", json={"email": "Admin@X.com", "name": "관리자"})
    assert r.status_code == 201 and r.json()["role"] == "admin"


async def login(client, services, email="admin@x.com"):
    await client.post("/api/auth/otp/request", json={"email": email})
    code = services.otp.provider.sent[-1][1]
    r = await client.post("/api/auth/otp/verify", json={"email": email, "code": code})
    assert r.status_code == 200
    client.csrf = r.json()["csrf_token"]
    return r


async def audit_events(services, cat):
    await services.log.flush()
    text = (services.paths.logs_dir / "2026-11-04.jsonl").read_text("utf-8")
    events = [json.loads(line) for line in text.splitlines()]
    return [e for e in events if e["cat"] == cat]


async def test_bootstrap_once(local_client):
    assert (await local_client.get("/api/bootstrap")).json() == {"needed": True}
    await bootstrap(local_client)
    r = await local_client.post("/api/bootstrap", json={"email": "b@x.com", "name": "b"})
    assert r.status_code == 409 and r.json() == {"error": "bootstrap_done"}


async def test_bootstrap_absent_on_external(external_client):
    assert (await external_client.post("/api/bootstrap", json={"email": "a@x.com", "name": "a"})).status_code == 404


async def test_login_with_mixed_case_email(local_client, services):
    await bootstrap(local_client)
    r = await login(local_client, services, " ADMIN@x.com ")
    cookie = r.headers["set-cookie"].lower()
    assert "mcpmon_sid=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    me = (await local_client.get("/api/auth/me")).json()
    assert me["user"]["email"] == "admin@x.com" and me["channel"] == "local"


async def test_request_unknown_email_same_response(local_client, services):
    await bootstrap(local_client)
    r = await local_client.post("/api/auth/otp/request", json={"email": "ghost@x.com"})
    assert r.status_code == 202 and services.otp.provider.sent == []


async def test_cooldown_429(local_client):
    await bootstrap(local_client)
    await local_client.post("/api/auth/otp/request", json={"email": "admin@x.com"})
    r = await local_client.post("/api/auth/otp/request", json={"email": "admin@x.com"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


async def test_wrong_code_401_and_audited(local_client, services):
    await bootstrap(local_client)
    await local_client.post("/api/auth/otp/request", json={"email": "admin@x.com"})
    code = services.otp.provider.sent[-1][1]
    wrong = "000000" if code != "000000" else "111111"
    r = await local_client.post("/api/auth/otp/verify", json={"email": "admin@x.com", "code": wrong})
    assert r.status_code == 401 and r.json() == {"error": "login_required"}
    await services.log.flush()
    text = (services.paths.logs_dir / "2026-11-04.jsonl").read_text("utf-8")
    assert '"cat": "auth"' in text and '"ok": false' in text


async def test_logout(local_client, services):
    await bootstrap(local_client)
    await login(local_client, services)
    assert (await local_client.get("/api/auth/me")).json()["user"] is not None
    assert (await local_client.post("/api/auth/logout")).status_code == 403  # CSRF 없음
    r = await local_client.post("/api/auth/logout", headers={"X-CSRF-Token": local_client.csrf})
    assert r.status_code == 204
    assert (await local_client.get("/api/auth/me")).json()["user"] is None


async def test_logout_without_session_is_204(local_client):
    r = await local_client.post("/api/auth/logout")
    assert r.status_code == 204


async def test_logout_revokes_server_side_and_audits(local_client, services):
    await bootstrap(local_client)
    await login(local_client, services)
    sid = local_client.cookies["mcpmon_sid"]
    r = await local_client.post("/api/auth/logout", headers={"X-CSRF-Token": local_client.csrf})
    assert r.status_code == 204
    assert services.sessions.get(sid, "local") is None
    assert "mcpmon_sid" in r.headers["set-cookie"].lower()
    events = [e for e in await audit_events(services, "auth") if e["event"] == "logout"]
    assert len(events) == 1 and events[0]["ok"] is True and events[0]["email"] == "admin@x.com"


async def test_login_response_shape_and_touch_login(local_client, services):
    await bootstrap(local_client)
    assert services.users.get_by_email("admin@x.com").last_login_at is None
    body = (await login(local_client, services)).json()
    assert set(body) == {"user", "csrf_token"}
    assert set(body["user"]) == {"id", "email", "name", "role"} and body["user"]["role"] == "admin"
    assert body["csrf_token"]
    assert services.users.get_by_email("admin@x.com").last_login_at is not None


async def test_login_revokes_preexisting_session(local_client, services, clock):
    await bootstrap(local_client)
    await login(local_client, services)
    old_sid = local_client.cookies["mcpmon_sid"]
    assert services.sessions.get(old_sid, "local") is not None
    clock.advance(61)  # past the resend cooldown
    await login(local_client, services)  # client still carries the old cookie
    new_sid = local_client.cookies["mcpmon_sid"]
    assert new_sid != old_sid
    assert services.sessions.get(old_sid, "local") is None
    assert services.sessions.get(new_sid, "local") is not None


async def test_failed_login_keeps_existing_session(local_client, services):
    await bootstrap(local_client)
    await login(local_client, services)
    sid = local_client.cookies["mcpmon_sid"]
    r = await local_client.post("/api/auth/otp/verify", json={"email": "admin@x.com", "code": "000000"})
    assert r.status_code == 401
    assert services.sessions.get(sid, "local") is not None


async def test_retry_after_value(local_client):
    await bootstrap(local_client)
    await local_client.post("/api/auth/otp/request", json={"email": "admin@x.com"})
    r = await local_client.post("/api/auth/otp/request", json={"email": "admin@x.com"})
    assert r.status_code == 429 and r.json() == {"error": "rate_limited"}
    assert r.headers["retry-after"] == "60"


async def test_otp_request_audited(local_client, services):
    await bootstrap(local_client)
    await local_client.post("/api/auth/otp/request", json={"email": " Admin@X.com "})
    await local_client.post("/api/auth/otp/request", json={"email": "admin@x.com"})  # cooldown
    await local_client.post("/api/auth/otp/request", json={"email": "not-an-email"})
    events = [e for e in await audit_events(services, "auth") if e["event"] == "otp_request"]
    assert [(e["email"], e["ok"]) for e in events] == [
        ("admin@x.com", True),
        ("admin@x.com", False),
        ("not-an-email", False),
    ]
    assert all(e["channel"] == "local" for e in events)


async def test_login_success_audited(local_client, services):
    await bootstrap(local_client)
    await login(local_client, services)
    events = [e for e in await audit_events(services, "auth") if e["event"] == "login"]
    assert len(events) == 1 and events[0]["ok"] is True and events[0]["email"] == "admin@x.com"


async def test_invalid_email_422(local_client):
    r = await local_client.post("/api/auth/otp/request", json={"email": "nope"})
    assert r.status_code == 422 and r.json() == {"error": "invalid_email"}
    r = await local_client.post("/api/bootstrap", json={"email": "nope", "name": "x"})
    assert r.status_code == 422 and r.json() == {"error": "invalid_email"}
    r = await local_client.post("/api/bootstrap", json={"email": "a@x.com", "name": "  "})
    assert r.status_code == 422 and r.json() == {"error": "validation"}
    assert (await local_client.get("/api/bootstrap")).json() == {"needed": True}


async def test_missing_fields_422_validation(local_client):
    r = await local_client.post("/api/auth/otp/verify", json={"email": "a@x.com"})
    assert r.status_code == 422 and r.json() == {"error": "validation"}


async def test_bootstrap_audited(local_client, services):
    await bootstrap(local_client)
    await local_client.post("/api/bootstrap", json={"email": "b@x.com", "name": "b"})
    events = [e for e in await audit_events(services, "admin.audit") if e["action"] == "bootstrap"]
    assert [e["result"] for e in events] == ["ok", "denied"]
    assert events[0]["actor_email"] == "admin@x.com" and events[0]["channel"] == "local"
    assert events[1]["actor_id"] is None


async def test_external_me_and_login(external_client, services):
    services.users.create_first_admin("admin@x.com", "관리자")
    me = (await external_client.get("/api/auth/me")).json()
    assert me == {"user": None, "channel": "external"}
    await login(external_client, services)
    me = (await external_client.get("/api/auth/me")).json()
    assert me["user"]["email"] == "admin@x.com" and me["channel"] == "external"


async def test_session_from_other_channel_is_anonymous(local_client, external_client, services):
    await bootstrap(local_client)
    await login(local_client, services)
    external_client.cookies.set("mcpmon_sid", local_client.cookies["mcpmon_sid"])
    assert (await external_client.get("/api/auth/me")).json()["user"] is None


async def test_cookie_secure_flag_follows_scheme(services):
    services.users.create_first_admin("admin@x.com", "관리자")
    app = create_app("external", services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        r = await login(client, services)
    assert "secure" in r.headers["set-cookie"].lower()


async def test_cookie_not_secure_over_http(external_client, services):
    services.users.create_first_admin("admin@x.com", "관리자")
    r = await login(external_client, services)
    assert "secure" not in r.headers["set-cookie"].lower()
