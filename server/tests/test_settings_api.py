import pytest

from app.auth import policy
from tests.test_auth_api import audit_events
from tests.test_auth_api import login as _login
from tests.test_users_api import admin_client


async def _settings_audit(services):
    return [e for e in await audit_events(services, "admin.audit") if e["action"] == "settings_update"]


async def test_get_and_update(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    assert (await c.get("/api/settings")).json()["log_retention_days"] == 180
    r = await c.put("/api/settings", json={"log_retention_days": 90, "ping_interval_sec": 10}, headers=h)
    assert r.status_code == 200 and r.json()["log_retention_days"] == 90
    assert services.settings.get().ping_interval_sec == 10


async def test_invalid_422(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    r = await c.put("/api/settings", json={"log_retention_days": 5}, headers=h)
    assert r.status_code == 422 and r.json() == {"error": "validation"}


async def test_absent_on_external(external_client):
    assert (await external_client.get("/api/settings")).status_code == 404


# --- additional coverage ---


@pytest.mark.parametrize(
    "body",
    [
        {"ping_interval_sec": "10"},          # strict: str is not int
        {"ping_interval_sec": True},          # strict: bool is not int
        {"ping_interval_sec": 10.0},          # strict: float is not int
        {"bogus": 1},                          # unknown key
        {"service_start_type": "sometimes"},  # bad literal
        {"log_compress_after_days": 181},     # compress > retention
        {"log_retention_days": 20, "log_compress_after_days": 30},
    ],
)
async def test_bad_bodies_422_and_unchanged(local_client, services, body):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    before = services.settings.get()
    r = await c.put("/api/settings", json=body, headers=h)
    assert r.status_code == 422 and r.json() == {"error": "validation"}
    assert services.settings.get() == before


async def test_non_object_body_422(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    r = await c.put("/api/settings", json=[1, 2], headers=h)
    assert r.status_code == 422 and r.json() == {"error": "validation"}


async def test_audit_records_only_changed_keys(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    r = await c.put(
        "/api/settings", json={"log_retention_days": 90, "ping_interval_sec": 5}, headers=h
    )
    assert r.status_code == 200
    (ev,) = await _settings_audit(services)
    assert ev["result"] == "ok" and ev["channel"] == "local" and ev["actor_email"] == "admin@x.com"
    assert ev["target"] == {"changes": {"log_retention_days": [180, 90]}}


async def test_noop_put_200_not_audited(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    assert (await c.put("/api/settings", json={}, headers=h)).status_code == 200
    r = await c.put("/api/settings", json={"ping_interval_sec": 5}, headers=h)
    assert r.status_code == 200 and r.json()["ping_interval_sec"] == 5
    assert await _settings_audit(services) == []


async def test_validation_failure_audited_as_error(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    await c.put("/api/settings", json={"log_retention_days": 5}, headers=h)
    (ev,) = await _settings_audit(services)
    assert ev["result"] == "error" and ev["target"] == {"error": "validation"}


async def test_retention_keys_require_edit_retention(local_client, services, monkeypatch):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    # Today EDIT_RETENTION == EDIT_GLOBAL_SETTINGS; make it unsatisfiable (owner required, none
    # given) to prove the extra check runs.
    monkeypatch.setitem(
        policy.RULES,
        policy.Action.EDIT_RETENTION,
        policy.Rule("admin", local_only=True, owner=policy.OwnerRule.ALWAYS),
    )
    r = await c.put("/api/settings", json={"log_retention_days": 90}, headers=h)
    assert r.status_code == 403 and r.json() == {"error": "forbidden"}
    r = await c.put("/api/settings", json={"log_compress_after_days": 10}, headers=h)
    assert r.status_code == 403
    assert services.settings.get().log_retention_days == 180
    # non-retention keys remain allowed
    r = await c.put("/api/settings", json={"ping_interval_sec": 7}, headers=h)
    assert r.status_code == 200
    denied = [
        e for e in await audit_events(services, "admin.audit")
        if e["action"] == "edit_retention" and e["result"] == "denied"
    ]
    assert len(denied) == 2


async def test_developer_forbidden(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    await c.post("/api/users", json={"email": "dev@x.com", "name": "d", "role": "developer"}, headers=h)
    await c.post("/api/auth/logout", headers=h)
    services.otp.provider.sent.clear(); services.clock.advance(61)
    await _login(c, services, "dev@x.com")
    h = {"X-CSRF-Token": c.csrf}
    assert (await c.get("/api/settings")).json() == {"error": "forbidden"}
    r = await c.put("/api/settings", json={"ping_interval_sec": 9}, headers=h)
    assert r.status_code == 403 and r.json() == {"error": "forbidden"}
    assert services.settings.get().ping_interval_sec == 5


async def test_anonymous_401(local_client):
    assert (await local_client.get("/api/settings")).status_code == 401
    assert (await local_client.put("/api/settings", json={})).status_code == 401


async def test_put_requires_csrf(local_client, services):
    c = await admin_client(local_client, services)
    r = await c.put("/api/settings", json={"ping_interval_sec": 9})
    assert r.status_code == 403 and r.json() == {"error": "csrf"}
    assert services.settings.get().ping_interval_sec == 5
