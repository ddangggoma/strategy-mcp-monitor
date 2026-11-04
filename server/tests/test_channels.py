import pytest
from starlette.routing import Match

from app.main import server_configs
from app.web import local_api
from app.web.app_factory import create_app


async def test_channel_reported(local_client, external_client):
    assert (await local_client.get("/api/channel")).json() == {"channel": "local"}
    assert (await external_client.get("/api/channel")).json() == {"channel": "external"}


def _serves(app, path: str, method: str) -> bool:
    # FastAPI >= 0.16x wraps include_router() output in _IncludedRouter objects that have
    # no `.path`, so ask the app's routes whether they would match instead of reading paths.
    scope = {"type": "http", "path": path, "method": method, "root_path": "", "headers": []}
    return any(r.matches(scope)[0] != Match.NONE for r in app.routes)


def test_local_routes_absent_on_external(services):
    local_only = [(r.path, sorted(r.methods)[0]) for r in local_api.router.routes]
    assert local_only
    local_app = create_app("local", services)
    external_app = create_app("external", services)
    for path, method in local_only:
        assert _serves(local_app, path, method)
        assert not _serves(external_app, path, method)


def test_bind_hosts(services):
    cfgs = server_configs(create_app("local", services), create_app("external", services))
    assert [(c.host, c.port) for c in cfgs] == [("127.0.0.1", 8700), ("0.0.0.0", 8701)]


async def test_bootstrap_needed_until_first_user(services, local_client, external_client):
    assert (await local_client.get("/api/bootstrap")).json() == {"needed": True}
    services.users.create("a@example.com", "A", "admin", None)
    assert (await local_client.get("/api/bootstrap")).json() == {"needed": False}
    assert (await external_client.get("/api/bootstrap")).status_code == 404


async def _host_client(app, host):
    import httpx

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8700",
        headers={"Host": host},
    )


async def test_local_rejects_foreign_host(services):
    app = create_app("local", services)
    async with await _host_client(app, "evil.example") as c:
        r = await c.get("/api/channel")
        assert r.status_code == 400 and r.json() == {"error": "bad_host"}
        r = await c.post("/api/bootstrap", json={"email": "a@x.com", "name": "a"})
        assert r.status_code == 400 and r.json() == {"error": "bad_host"}
    assert services.users.count() == 0


@pytest.mark.parametrize(
    "host",
    ["localhost:8700", "127.0.0.1", "LocalHost", "127.0.0.1:8700", "[::1]:8700", "[::1]"],
)
async def test_local_accepts_loopback_hosts(services, host):
    async with await _host_client(create_app("local", services), host) as c:
        assert (await c.get("/api/channel")).json() == {"channel": "local"}


@pytest.mark.parametrize(
    "host", ["127.0.0.1.evil.example", "evil.example:8700", "localhost.evil.example", "evil@127.0.0.1", ""]
)
async def test_local_rejects_lookalike_hosts(services, host):
    async with await _host_client(create_app("local", services), host) as c:
        assert (await c.get("/api/channel")).status_code == 400


async def test_external_does_not_restrict_host(services):
    async with await _host_client(create_app("external", services), "evil.example") as c:
        r = await c.get("/api/channel")
        assert r.status_code == 200 and r.json() == {"channel": "external"}
