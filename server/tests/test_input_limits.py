import pytest

from tests.test_auth_api import audit_events, bootstrap

# Ruling F20: the body cap is 524_288 (not 262_144) so a legitimate POST /api/mcps with
# three maximal scripts (65_536 B each, JSON-escaped) still fits.
MAX_BODY = 524_288


async def test_user_agent_capped_in_audit_and_session(local_client, services):
    await bootstrap(local_client)
    ua = {"User-Agent": "A" * 5000}
    await local_client.post("/api/auth/otp/request", json={"email": "admin@x.com"}, headers=ua)
    code = services.otp.provider.sent[-1][1]
    r = await local_client.post("/api/auth/otp/verify", json={"email": "admin@x.com", "code": code}, headers=ua)
    assert r.status_code == 200
    events = await audit_events(services, "auth")
    assert events and all(len(e["user_agent"]) == 512 for e in events)
    assert len(services.db.query("SELECT user_agent FROM auth_sessions")[0]["user_agent"]) == 512


@pytest.mark.parametrize("path,body", [
    ("/api/auth/otp/request", {"email": "a@x.com", "x": 1}),
    ("/api/auth/otp/verify", {"email": "a@x.com", "code": "123456", "x": 1}),
])
async def test_otp_bodies_forbid_extra(external_client, path, body):
    r = await external_client.post(path, json=body)
    assert r.status_code == 422 and r.json() == {"error": "validation"}


async def test_max_body_bytes_constant():
    from app.web.app_factory import MAX_BODY_BYTES
    assert MAX_BODY_BYTES == MAX_BODY


async def test_body_too_large_413(external_client):
    r = await external_client.post("/api/auth/otp/request", content=b"{" + b" " * MAX_BODY + b"}",
                                   headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json() == {"error": "body_too_large"}


async def test_body_at_limit_is_accepted(external_client):
    head, tail = b'{"email":"a@x.com"', b"}"
    r = await external_client.post("/api/auth/otp/request",
                                   content=head + b" " * (MAX_BODY - len(head) - len(tail)) + tail,
                                   headers={"Content-Type": "application/json"})
    assert r.status_code != 413


async def test_chunked_body_too_large_413(local_client):
    async def chunks():
        for _ in range(9):  # 9 * 65_536 > 524_288
            yield b" " * 65_536
    r = await local_client.post("/api/bootstrap", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json() == {"error": "body_too_large"}
