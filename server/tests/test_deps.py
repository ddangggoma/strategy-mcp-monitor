import json

import httpx
import pytest
from fastapi import APIRouter, Depends

from app.auth.policy import Action
from app.web.app_factory import create_app
from app.web.deps import check_csrf, current_user, require


def _make_app(channel, services):
    app = create_app(channel, services)
    r = APIRouter(prefix="/t")

    @r.get("/me")
    async def me(user=Depends(current_user)):
        return {"email": user.email if user else None}

    @r.get("/board")
    async def board(user=Depends(require(Action.VIEW_BOARD))):
        return {"ok": True}

    @r.get("/logs")
    async def logs(user=Depends(require(Action.VIEW_LOGS))):
        return {"ok": True}

    @r.post("/users")
    async def users(user=Depends(require(Action.MANAGE_USERS))):
        return {"ok": True}

    @r.post("/board")
    async def board_post(user=Depends(require(Action.VIEW_BOARD))):
        return {"ok": True}

    @r.post("/mcp/{owner}")
    async def edit(
        owner: str,
        user=Depends(
            require(Action.EDIT_SCRIPTS, owner_id=lambda req: int(req.path_params["owner"]))
        ),
    ):
        return {"ok": True}

    @r.post("/logout")
    async def logout(_=Depends(check_csrf)):
        return {"ok": True}

    app.include_router(r)
    return app


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _login(services, client, role="developer", channel="local", email="u@example.com"):
    user = services.users.create(email, "U", role, None)
    sid, csrf = services.sessions.create(user.id, channel, "127.0.0.1", "ua")
    client.cookies.set("mcpmon_sid", sid)
    return user, csrf


async def _audit_lines(services):
    await services.log.flush()
    lines = []
    for f in services.paths.logs_dir.glob("*.jsonl"):
        lines += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]
    return [e for e in lines if e["cat"] == "admin.audit"]


async def test_current_user_anonymous_and_valid(services):
    async with _client(_make_app("local", services)) as c:
        assert (await c.get("/t/me")).json() == {"email": None}
        _login(services, c)
        assert (await c.get("/t/me")).json() == {"email": "u@example.com"}


async def test_current_user_none_for_inactive_user(services):
    async with _client(_make_app("local", services)) as c:
        user, _ = _login(services, c)
        services.users.create("b@example.com", "B", "admin", None)  # keep an admin around
        services.users.set_active(user.id, False)
        assert (await c.get("/t/me")).json() == {"email": None}
        r = await c.get("/t/logs")
        assert r.status_code == 401 and r.json() == {"error": "login_required"}


async def test_current_user_rejects_session_from_other_channel(services):
    async with _client(_make_app("external", services)) as c:
        _login(services, c, channel="local")
        assert (await c.get("/t/me")).json() == {"email": None}


async def test_anonymous_denied_is_401_and_audited(services):
    async with _client(_make_app("local", services)) as c:
        r = await c.get("/t/logs")
    assert r.status_code == 401 and r.json() == {"error": "login_required"}
    [e] = await _audit_lines(services)
    assert e["result"] == "denied" and e["actor_id"] is None and e["actor_email"] is None
    assert e["action"] == "view_logs" and e["channel"] == "local"
    assert e["ip"] == "127.0.0.1" and e["target"] == {"path": "/t/logs"}


async def test_forbidden_is_403_and_audited(services):
    async with _client(_make_app("local", services)) as c:
        user, csrf = _login(services, c, role="developer")
        r = await c.post("/t/users", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 403 and r.json() == {"error": "forbidden"}
    [e] = await _audit_lines(services)
    assert e["actor_id"] == user.id and e["actor_email"] == user.email and e["result"] == "denied"


async def test_local_only_action_forbidden_on_external(services):
    async with _client(_make_app("external", services)) as c:
        _, csrf = _login(services, c, role="admin", channel="external")
        r = await c.post("/t/users", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 403 and r.json() == {"error": "forbidden"}


async def test_allowed_passes_without_audit(services):
    async with _client(_make_app("local", services)) as c:
        _, csrf = _login(services, c, role="admin")
        assert (await c.get("/t/logs")).status_code == 200
        assert (await c.post("/t/users", headers={"X-CSRF-Token": csrf})).status_code == 200
    assert await _audit_lines(services) == []


@pytest.mark.parametrize("headers", [{}, {"X-CSRF-Token": "wrong"}])
async def test_unsafe_method_with_bad_csrf_is_403_csrf(services, headers):
    async with _client(_make_app("local", services)) as c:
        _login(services, c, role="admin")
        r = await c.post("/t/users", headers=headers)
    assert r.status_code == 403 and r.json() == {"error": "csrf"}


async def test_safe_method_needs_no_csrf(services):
    async with _client(_make_app("local", services)) as c:
        _login(services, c)
        assert (await c.get("/t/board")).status_code == 200


async def test_anonymous_post_needs_no_csrf(services):
    async with _client(_make_app("local", services)) as c:
        assert (await c.post("/t/board")).status_code == 200
        assert (await c.post("/t/users")).status_code == 401


async def test_owner_rule_uses_owner_id_callable(services):
    async with _client(_make_app("local", services)) as c:
        user, csrf = _login(services, c, role="developer")
        h = {"X-CSRF-Token": csrf}
        assert (await c.post(f"/t/mcp/{user.id}", headers=h)).status_code == 200
        r = await c.post(f"/t/mcp/{user.id + 99}", headers=h)
    assert r.status_code == 403 and r.json() == {"error": "forbidden"}


async def test_check_csrf_helper(services):
    async with _client(_make_app("local", services)) as c:
        assert (await c.post("/t/logout")).status_code == 200  # no session: nothing to check
        _, csrf = _login(services, c)
        r = await c.post("/t/logout", headers={"X-CSRF-Token": "nope"})
        assert r.status_code == 403 and r.json() == {"error": "csrf"}
        assert (await c.post("/t/logout", headers={"X-CSRF-Token": csrf})).status_code == 200


async def test_csrf_rejection_is_audited(services):
    async with _client(_make_app("local", services)) as c:
        user, _ = _login(services, c, role="admin")
        r = await c.post("/t/users", headers={"X-CSRF-Token": "wrong"})
        assert r.status_code == 403 and r.json() == {"error": "csrf"}
        r = await c.post("/t/logout")
        assert r.status_code == 403
    first, second = await _audit_lines(services)
    assert first["action"] == "manage_users" and first["result"] == "denied"
    assert first["actor_id"] == user.id and first["ip"] == "127.0.0.1"
    assert first["target"] == {"path": "/t/users", "reason": "csrf"}
    assert second["action"] == "csrf" and second["target"] == {"path": "/t/logout", "reason": "csrf"}


async def test_owner_callable_not_evaluated_for_anonymous(services):
    app = _make_app("local", services)
    async with _client(app) as c:
        r = await c.post("/t/mcp/not-a-number")
    assert r.status_code == 401 and r.json() == {"error": "login_required"}


async def test_owner_callable_value_error_is_422_validation(services):
    async with _client(_make_app("local", services)) as c:
        _, csrf = _login(services, c, role="developer")
        r = await c.post("/t/mcp/not-a-number", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 422 and r.json() == {"error": "validation"}
