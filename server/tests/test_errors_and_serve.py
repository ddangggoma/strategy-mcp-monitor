import httpx
from fastapi import APIRouter

from app.main import request_exit, server_configs
from app.services import build_services
from app.web.app_factory import create_app


class _FakeServer:
    def __init__(self):
        self.should_exit = False
        self.force_exit = False


def test_first_signal_graceful_second_forces_exit():
    servers = [_FakeServer(), _FakeServer()]
    request_exit(servers)
    assert all(s.should_exit and not s.force_exit for s in servers)
    request_exit(servers)
    assert all(s.should_exit and s.force_exit for s in servers)


def test_server_configs_ignore_proxy_headers_and_bound_shutdown(services):
    cfgs = server_configs(create_app("local", services), create_app("external", services))
    assert all(c.proxy_headers is False for c in cfgs)
    assert all(c.timeout_graceful_shutdown == 10 for c in cfgs)


async def test_framework_errors_use_error_code_bodies(external_client):
    r = await external_client.get("/api/bootstrap")
    assert r.status_code == 404 and r.json() == {"error": "not_found"}
    r = await external_client.post("/api/channel")
    assert r.status_code == 405 and r.json() == {"error": "method_not_allowed"}


async def test_unhandled_exception_is_500_internal(services, capsys):
    app = create_app("local", services)
    router = APIRouter()

    @router.get("/t/boom")
    async def boom():
        raise RuntimeError("secret detail")

    @router.get("/t/num/{n}")
    async def num(n: int):
        return {"n": n}

    app.include_router(router)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/t/boom")
        assert r.status_code == 500 and r.json() == {"error": "internal"}
        assert "secret detail" not in r.text
        r = await c.get("/t/num/abc")
        assert r.status_code == 422 and r.json() == {"error": "validation"}
    assert "secret detail" in capsys.readouterr().err


def test_build_services_reuses_stored_otp_secret(tmp_path):
    first = build_services(tmp_path)
    secret1 = first.db.query("SELECT value FROM secrets WHERE name = 'otp_secret'")[0]["value"]
    first.db.close()
    second = build_services(tmp_path)
    rows = second.db.query("SELECT value FROM secrets WHERE name = 'otp_secret'")
    second.db.close()
    assert len(rows) == 1 and rows[0]["value"] == secret1
    assert len(bytes.fromhex(secret1)) == 32
