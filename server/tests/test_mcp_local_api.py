import asyncio

import pytest

from tests.mcp_helpers import BAT, login_as, make_user, seed_mcp
from tests.test_auth_api import audit_events

SCRIPTS = {"start": {"ext": ".bat", "content": "exit /b 0"}, "stop": {"ext": ".bat", "content": "exit /b 0"}}
BODY = {"name": "calc", "host": "127.0.0.1", "port": 9102, "scripts": SCRIPTS}
BIG = 2**63 - 1


async def as_user(client, services, email, role="developer", channel="local"):
    u = make_user(services, email, role); return u, {"X-CSRF-Token": login_as(client, services, u, channel)}


async def admin_events(services, action):
    return [e for e in await audit_events(services, "admin.audit") if e["action"] == action]


async def test_create_owner_is_creator(local_client, services):
    dev, h = await as_user(local_client, services, "dev@x.com")
    r = await local_client.post("/api/mcps", json=BODY, headers=h)
    assert r.status_code == 201 and r.json()["owner"]["id"] == dev.id
    mid = r.json()["id"]
    assert (services.paths.scripts_dir / str(mid) / "start.bat").exists() and services.monitor.engine(mid) is not None
    assert r.json()["live"]["id"] == mid and r.json()["port"] == 9102
    ev = (await audit_events(services, "admin.audit"))[-1]
    assert (ev["action"], ev["result"], ev["target"]) == ("mcp_create", "ok", {"mcp_id": mid, "name": "calc", "host": "127.0.0.1", "port": 9102})


async def test_create_requires_both_scripts(local_client, services):
    _, h = await as_user(local_client, services, "dev@x.com")
    r = await local_client.post("/api/mcps", json={**BODY, "scripts": {"start": SCRIPTS["start"]}}, headers=h)
    assert r.status_code == 422 and r.json() == {"error": "scripts_required"} and services.mcps.list() == []
    for scripts in ({"stop": SCRIPTS["stop"]}, {"restart": SCRIPTS["start"]}, {}):
        r = await local_client.post("/api/mcps", json={**BODY, "scripts": scripts}, headers=h)
        assert (r.status_code, r.json()) == (422, {"error": "scripts_required"})
    no_scripts = {k: v for k, v in BODY.items() if k != "scripts"}
    assert (await local_client.post("/api/mcps", json=no_scripts, headers=h)).json() == {"error": "scripts_required"}
    big = {**SCRIPTS, "start": {"ext": ".ps1", "content": "가" * 30_000}}
    assert (await local_client.post("/api/mcps", json={**BODY, "scripts": big}, headers=h)).json() == {"error": "script_too_large"}
    assert services.mcps.list() == [] and not list(services.paths.scripts_dir.iterdir())
    errs = [e["target"]["error"] for e in await admin_events(services, "mcp_create")]
    assert errs == ["scripts_required"] * 5 + ["script_too_large"]
    assert {e["result"] for e in await admin_events(services, "mcp_create")} == {"error"}


async def test_create_script_validation_codes(local_client, services):
    _, h = await as_user(local_client, services, "dev@x.com")

    async def post(**over):
        return await local_client.post("/api/mcps", json={**BODY, "scripts": {**SCRIPTS, **over}}, headers=h)

    assert (await post(stop={"ext": ".bat", "content": "  \r\n"})).json() == {"error": "script_empty"}
    assert (await post(stop={"ext": ".bat", "content": "echo \U0001f600"})).json() == {"error": "script_encoding"}
    for bad in ({"ext": ".sh", "content": "x"}, {"ext": ".bat"}, {"ext": ".bat", "content": "x", "mode": 1},
                {"ext": ".bat", "content": "x" * 65_537}, "exit /b 0", None):
        r = await post(stop=bad)
        assert (r.status_code, r.json()) == (422, {"error": "validation"}), bad
    assert (await post(deploy={"ext": ".bat", "content": "x"})).json() == {"error": "validation"}
    assert services.mcps.list() == []


async def test_create_validation_and_conflicts(local_client, services):
    _, h = await as_user(local_client, services, "dev@x.com")
    for body in ({**BODY, "port": 0}, {**BODY, "extra": 1}, {**BODY, "name": ""}, {**BODY, "scripts": "x"}, [1]):
        r = await local_client.post("/api/mcps", json=body, headers=h)
        assert (r.status_code, r.json()) == (422, {"error": "validation"}), body
    assert (await local_client.post("/api/mcps", json=BODY, headers=h)).status_code == 201
    r = await local_client.post("/api/mcps", json={**BODY, "name": "CALC", "port": 9999}, headers=h)
    assert (r.status_code, r.json()) == (409, {"error": "name_taken"})
    r = await local_client.post("/api/mcps", json={**BODY, "name": "other"}, headers=h)
    assert (r.status_code, r.json()) == (409, {"error": "endpoint_taken"})
    assert len(services.mcps.list()) == 1 and len(list(services.paths.scripts_dir.iterdir())) == 1
    assert len(services.monitor.board()) == 1
    ev = await admin_events(services, "mcp_create")
    assert [(e["result"], e["target"].get("error")) for e in ev[-3:]] == [("ok", None), ("error", "name_taken"), ("error", "endpoint_taken")]


async def test_local_methods_404_on_external(external_client, services):
    dev, h = await as_user(external_client, services, "dev@x.com", channel="external"); m = seed_mcp(services, dev)
    for method, path in (("POST", "/api/mcps"), ("DELETE", f"/api/mcps/{m.id}"), ("PUT", f"/api/mcps/{m.id}/scripts/start"),
                         ("GET", f"/api/mcps/{m.id}/scripts/start"), ("POST", f"/api/mcps/{m.id}/owner")):
        r = await external_client.request(method, path, json={}, headers=h)
        assert r.status_code == 404 and r.json() == {"error": "not_found"}, (method, path)
        assert "allow" not in r.headers  # the 405 Allow header would reveal the route
    assert services.mcps.get(m.id) is not None


async def test_script_edit_owner_only(local_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    for email, role in (("b@x.com", "developer"), ("adm@x.com", "admin")):
        _, h = await as_user(local_client, services, email, role)
        assert (await local_client.put(f"/api/mcps/{m.id}/scripts/start", json={"ext": ".bat", "content": "exit /b 1"}, headers=h)).json() == {"error": "forbidden"}
        g = (await local_client.get(f"/api/mcps/{m.id}/scripts/start")).json()
        assert g["editable"] is False and g["content"] == "exit /b 0\r\n"
    assert services.scripts.get(m.id, "start").version == 1
    den = [e for e in await audit_events(services, "admin.audit") if e["action"] == "edit_scripts"]
    assert [e["result"] for e in den] == ["denied", "denied"]


async def test_script_versions_revert_delete(local_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner); h = {"X-CSRF-Token": login_as(local_client, services, owner, "local")}
    r = await local_client.put(f"/api/mcps/{m.id}/scripts/start", json={"ext": ".ps1", "content": "exit 0"}, headers=h)
    assert r.json()["version"] == 2
    vs = (await local_client.get(f"/api/mcps/{m.id}/scripts/start/versions")).json()
    assert [v["version"] for v in vs] == [2, 1]
    assert (await local_client.get(f"/api/mcps/{m.id}/scripts/start/versions/1")).json()["content"] == "exit /b 0\r\n"
    r = await local_client.post(f"/api/mcps/{m.id}/scripts/start/versions/1/revert", headers=h)
    assert (r.json()["version"], r.json()["ext"]) == (3, ".bat")
    assert (await local_client.delete(f"/api/mcps/{m.id}/scripts/start", headers=h)).json() == {"error": "script_required"}
    assert (await local_client.delete(f"/api/mcps/{m.id}/scripts/restart", headers=h)).status_code == 404
    acts = [e["action"] for e in await audit_events(services, "admin.audit")]
    assert "script_update" in acts and "script_revert" in acts


async def test_script_crud_shapes_and_files(local_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner); h = {"X-CSRF-Token": login_as(local_client, services, owner, "local")}
    base = f"/api/mcps/{m.id}/scripts"
    lst = (await local_client.get(base)).json()
    assert [s["kind"] for s in lst] == ["start", "stop"]
    assert set(lst[0]) == {"kind", "ext", "version", "sha256", "updated_at", "updated_by"} and lst[0]["updated_by"] == owner.id
    g = (await local_client.get(f"{base}/start")).json()
    assert set(g) == {"kind", "ext", "version", "sha256", "content", "editable"} and g["editable"] is True
    assert (await local_client.get(f"{base}/restart")).status_code == 404
    # add restart, swap start to .ps1 (the .bat file goes away)
    r = await local_client.put(f"{base}/restart", json={"ext": ".cmd", "content": "exit /b 0"}, headers=h)
    assert (r.status_code, set(r.json()), r.json()["version"]) == (200, {"kind", "ext", "version", "sha256"}, 1)
    r = await local_client.put(f"{base}/start", json={"ext": ".ps1", "content": "exit 0"}, headers=h)
    d = services.paths.scripts_dir / str(m.id)
    assert r.json()["sha256"] == services.scripts.get(m.id, "start").sha256
    assert (d / "start.ps1").exists() and not (d / "start.bat").exists() and (d / "restart.cmd").exists()
    # delete restart: version history keeps a tombstone
    assert (await local_client.delete(f"{base}/restart", headers=h)).status_code == 204
    assert (await local_client.get(f"{base}/restart")).status_code == 404 and not (d / "restart.cmd").exists()
    vs = (await local_client.get(f"{base}/restart/versions")).json()
    assert [(v["version"], v["deleted"]) for v in vs] == [(2, True), (1, False)]
    assert set(vs[0]) == {"version", "ext", "sha256", "author_id", "created_at", "deleted"} and vs[0]["sha256"] is None
    one = (await local_client.get(f"{base}/restart/versions/1")).json()
    assert set(one) == {"version", "ext", "sha256", "author_id", "created_at", "deleted", "content"} and one["ext"] == ".cmd"
    # reverting a deleted tombstone is refused, reverting a real one restores the script
    assert (await local_client.post(f"{base}/restart/versions/2/revert", headers=h)).json() == {"error": "validation"}
    r = await local_client.post(f"{base}/restart/versions/1/revert", headers=h)
    assert (r.status_code, r.json()["version"], r.json()["ext"]) == (200, 3, ".cmd") and (d / "restart.cmd").exists()
    ev = {a: await admin_events(services, a) for a in ("script_update", "script_delete", "script_revert")}
    assert [e["target"]["kind"] for e in ev["script_update"]] == ["restart", "start"]
    assert ev["script_update"][1]["target"] == {"mcp_id": m.id, "kind": "start", "version": 2, "sha256": r_sha(services, m.id, "start")}
    assert ev["script_delete"][0]["target"] == {"mcp_id": m.id, "kind": "restart"}
    assert [(e["result"], e["target"].get("error")) for e in ev["script_revert"]] == [("error", "validation"), ("ok", None)]
    assert ev["script_revert"][1]["target"] == {"mcp_id": m.id, "kind": "restart", "from_version": 1, "version": 3}


def r_sha(services, mcp_id, kind):
    return services.scripts.get(mcp_id, kind).sha256


async def test_script_put_validation_and_missing(local_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner); h = {"X-CSRF-Token": login_as(local_client, services, owner, "local")}
    url = f"/api/mcps/{m.id}/scripts/start"
    for body, code in (({"ext": ".bat", "content": " "}, "script_empty"), ({"ext": ".bat", "content": "\U0001f600"}, "script_encoding"),
                       ({"ext": ".ps1", "content": "가" * 30_000}, "script_too_large"), ({"ext": ".sh", "content": "x"}, "validation"),
                       ({"ext": ".bat", "content": "x", "kind": "stop"}, "validation"), ({"ext": ".bat"}, "validation"), ({}, "validation")):
        r = await local_client.put(url, json=body, headers=h)
        assert (r.status_code, r.json()) == (422, {"error": code}), body
    assert (await local_client.put(f"/api/mcps/{m.id}/scripts/deploy", json={"ext": ".bat", "content": "x"}, headers=h)).json() == {"error": "validation"}
    assert (await local_client.put("/api/mcps/999/scripts/start", json={"ext": ".bat", "content": "x"}, headers=h)).json() == {"error": "not_found"}
    assert services.scripts.get(m.id, "start").version == 1
    ev = await admin_events(services, "script_update")
    assert len(ev) == 7 and {e["result"] for e in ev} == {"error"}


async def test_owner_transfer(local_client, services):
    a = make_user(services, "a@x.com"); b = make_user(services, "b@x.com"); m = seed_mcp(services, a)
    _, hd = await as_user(local_client, services, "d@x.com")
    assert (await local_client.post(f"/api/mcps/{m.id}/owner", json={"user_id": b.id}, headers=hd)).json() == {"error": "forbidden"}
    _, h = await as_user(local_client, services, "adm@x.com", "admin")
    assert (await local_client.post(f"/api/mcps/{m.id}/owner", json={"user_id": 9999}, headers=h)).json() == {"error": "invalid_owner"}
    r = await local_client.post(f"/api/mcps/{m.id}/owner", json={"user_id": b.id}, headers=h)
    assert r.status_code == 200 and r.json()["owner"]["id"] == b.id
    hb = {"X-CSRF-Token": login_as(local_client, services, b, "local")}
    assert (await local_client.put(f"/api/mcps/{m.id}/scripts/stop", json={"ext": ".bat", "content": "exit /b 0"}, headers=hb)).status_code == 200
    ha = {"X-CSRF-Token": login_as(local_client, services, a, "local")}  # the previous owner lost the right
    assert (await local_client.put(f"/api/mcps/{m.id}/scripts/stop", json={"ext": ".bat", "content": "exit /b 0"}, headers=ha)).json() == {"error": "forbidden"}
    assert services.monitor._config[m.id].owner_id == b.id
    ev = await admin_events(services, "mcp_owner_transfer")
    assert [(e["result"], e["target"]) for e in ev] == [("error", {"mcp_id": m.id, "error": "invalid_owner"}), ("ok", {"mcp_id": m.id, "from": a.id, "to": b.id})]


async def test_owner_transfer_rejects_bad_targets(local_client, services):
    a = make_user(services, "a@x.com"); gone = make_user(services, "gone@x.com"); m = seed_mcp(services, a)
    services.users.set_active(gone.id, False)
    _, h = await as_user(local_client, services, "adm@x.com", "admin")
    url = f"/api/mcps/{m.id}/owner"
    r = await local_client.post(url, json={"user_id": gone.id}, headers=h)
    assert (r.status_code, r.json()) == (422, {"error": "invalid_owner"})
    for body in ({"user_id": 0}, {"user_id": -1}, {"user_id": BIG + 1}, {"user_id": 2**70}, {"user_id": "1"}, {"user_id": True},
                 {"user_id": a.id, "x": 1}, {}, []):
        r = await local_client.post(url, json=body, headers=h)
        assert (r.status_code, r.json()) == (422, {"error": "validation"}), body
    assert (await local_client.post("/api/mcps/999/owner", json={"user_id": a.id}, headers=h)).json() == {"error": "not_found"}
    assert services.mcps.get(m.id).owner_id == a.id
    # a deactivated MCP owner can be replaced by an admin
    services.users.set_active(a.id, False)
    b = make_user(services, "b@x.com")
    assert (await local_client.post(url, json={"user_id": b.id}, headers=h)).json()["owner"]["id"] == b.id


async def test_inactive_owner_shows_no_owner(local_client, services):
    a = make_user(services, "a@x.com"); m = seed_mcp(services, a); _, h = await as_user(local_client, services, "adm@x.com", "admin")
    services.users.set_active(a.id, False)
    assert (await local_client.get(f"/api/mcps/{m.id}")).json()["owner"] is None
    assert (await local_client.put(f"/api/mcps/{m.id}/scripts/start", json={"ext": ".bat", "content": "x"}, headers=h)).json() == {"error": "forbidden"}


async def test_delete_mcp(local_client, services):
    a = make_user(services, "a@x.com"); m = seed_mcp(services, a)
    _, hb = await as_user(local_client, services, "b@x.com")
    assert (await local_client.delete(f"/api/mcps/{m.id}", headers=hb)).json() == {"error": "forbidden"}
    assert (await local_client.delete("/api/mcps/999", headers=hb)).json() == {"error": "not_found"}
    assert (await local_client.put("/api/mcps/abc/scripts/start", json={}, headers=hb)).json() == {"error": "validation"}
    assert (await local_client.delete(f"/api/mcps/{2**70}", headers=hb)).status_code == 422
    ha = {"X-CSRF-Token": login_as(local_client, services, a, "local")}
    assert (await local_client.delete(f"/api/mcps/{m.id}", headers=ha)).status_code == 204
    assert services.mcps.get(m.id) is None and not (services.paths.scripts_dir / str(m.id)).exists()
    assert services.monitor.board() == []
    assert services.monitor._runner.calls == []  # the stop script is never run on delete
    ev = (await admin_events(services, "mcp_delete"))[-1]
    assert (ev["result"], ev["target"]) == ("ok", {"mcp_id": m.id, "name": "calc"})


async def test_admin_may_delete_any_and_ownerless(local_client, services):
    a = make_user(services, "a@x.com"); m = seed_mcp(services, a); services.users.set_active(a.id, False)
    _, h = await as_user(local_client, services, "adm@x.com", "admin")
    assert (await local_client.delete(f"/api/mcps/{m.id}", headers=h)).status_code == 204
    assert services.mcps.list() == []


async def test_delete_refused_while_action_runs(local_client, services):
    a = make_user(services, "a@x.com"); m = seed_mcp(services, a)
    h = {"X-CSRF-Token": login_as(local_client, services, a, "local")}
    services.monitor._runner.gate = asyncio.Event()
    assert (await local_client.post(f"/api/mcps/{m.id}/actions/start", headers=h)).status_code == 202
    r = await local_client.delete(f"/api/mcps/{m.id}", headers=h)
    assert (r.status_code, r.json()) == (409, {"error": "action_in_progress"})
    assert services.mcps.get(m.id) is not None and (services.paths.scripts_dir / str(m.id)).exists()
    assert services.monitor.engine(m.id) is not None
    services.monitor._runner.gate.set(); await services.monitor.wait_idle()
    assert (await local_client.delete(f"/api/mcps/{m.id}", headers=h)).status_code == 204
    ev = await admin_events(services, "mcp_delete")
    assert [(e["result"], e["target"].get("error")) for e in ev] == [("error", "action_in_progress"), ("ok", None)]


async def test_version_and_kind_bounds(local_client, services):
    a = make_user(services, "a@x.com"); m = seed_mcp(services, a); h = {"X-CSRF-Token": login_as(local_client, services, a, "local")}
    base = f"/api/mcps/{m.id}/scripts"
    for v in (0, -1, BIG + 1, 2**70):
        assert (await local_client.get(f"{base}/start/versions/{v}")).status_code == 422, v
        assert (await local_client.post(f"{base}/start/versions/{v}/revert", headers=h)).status_code == 422, v
    assert (await local_client.get(f"{base}/start/versions/abc")).status_code == 422
    assert (await local_client.get(f"{base}/start/versions/99")).json() == {"error": "not_found"}
    assert (await local_client.post(f"{base}/start/versions/99/revert", headers=h)).json() == {"error": "not_found"}
    assert (await local_client.get(f"{base}/start/versions/{BIG}")).json() == {"error": "not_found"}
    assert (await local_client.get(f"{base}/bogus")).status_code == 422
    assert (await local_client.get(f"{base}/bogus/versions")).status_code == 422
    assert (await local_client.get(f"{base}/restart/versions")).json() == []
    assert (await local_client.get("/api/mcps/999/scripts")).json() == {"error": "not_found"}
    assert (await local_client.get("/api/mcps/999/scripts/start/versions")).json() == {"error": "not_found"}


# ---- permission matrix ---------------------------------------------------------------

# route -> expected status for (anonymous, owner, other developer, non-owner admin) on the local channel
ROUTES = {
    "create": ("POST", "/api/mcps", (401, 201, 201, 201)),
    "delete": ("DELETE", "/api/mcps/{id}", (401, 204, 403, 204)),
    "transfer": ("POST", "/api/mcps/{id}/owner", (401, 403, 403, 200)),
    "list_scripts": ("GET", "/api/mcps/{id}/scripts", (401, 200, 200, 200)),
    "get_script": ("GET", "/api/mcps/{id}/scripts/start", (401, 200, 200, 200)),
    "put_script": ("PUT", "/api/mcps/{id}/scripts/start", (401, 200, 403, 403)),
    "delete_script": ("DELETE", "/api/mcps/{id}/scripts/restart", (401, 204, 403, 403)),
    "versions": ("GET", "/api/mcps/{id}/scripts/start/versions", (401, 200, 200, 200)),
    "version": ("GET", "/api/mcps/{id}/scripts/start/versions/1", (401, 200, 200, 200)),
    "revert": ("POST", "/api/mcps/{id}/scripts/start/versions/1/revert", (401, 200, 403, 403)),
}
PERSONAS = ("anonymous", "owner", "developer", "admin")


def request_for(name, mcp, owner):
    body = {
        "create": {**BODY, "name": "n2", "port": 9202},
        "transfer": {"user_id": owner.id},
        "put_script": {"ext": ".bat", "content": "exit /b 0"},
    }.get(name)
    method, path, _ = ROUTES[name]
    return method, path.replace("{id}", str(mcp.id)), body


async def prepare(services, client, persona, channel):
    owner = make_user(services, "o@x.com")
    m = seed_mcp(services, owner, scripts={**BAT, "restart": BAT["start"]})
    user = {"anonymous": None, "owner": owner, "developer": make_user(services, "d@x.com"), "admin": make_user(services, "adm@x.com", "admin")}[persona]
    headers = {"X-CSRF-Token": login_as(client, services, user, channel)} if user else {}
    return owner, m, headers


@pytest.mark.parametrize("persona", PERSONAS)
@pytest.mark.parametrize("name", ROUTES)
async def test_permission_matrix_local(name, persona, local_client, services):
    owner, m, headers = await prepare(services, local_client, persona, "local")
    method, path, body = request_for(name, m, owner)
    r = await local_client.request(method, path, json=body, headers=headers)
    expected = ROUTES[name][2][PERSONAS.index(persona)]
    assert r.status_code == expected, (name, persona, r.text)
    if expected == 401:
        assert r.json() == {"error": "login_required"}
    elif expected == 403:
        assert r.json() == {"error": "forbidden"}


@pytest.mark.parametrize("persona", PERSONAS)
@pytest.mark.parametrize("name", ROUTES)
async def test_permission_matrix_external_is_404(name, persona, external_client, services):
    owner, m, headers = await prepare(services, external_client, persona, "external")
    method, path, body = request_for(name, m, owner)
    before = (services.mcps.list(), services.scripts.list(m.id))
    r = await external_client.request(method, path, json=body, headers=headers)
    assert (r.status_code, r.json()) == (404, {"error": "not_found"}), (name, persona)
    assert (services.mcps.list(), services.scripts.list(m.id)) == before


MUTATING = [n for n, (method, _, _) in ROUTES.items() if method != "GET"]


@pytest.mark.parametrize("bad", [None, "wrong"])
@pytest.mark.parametrize("name", MUTATING)
async def test_csrf_required_on_every_mutation(name, bad, local_client, services):
    owner, m, _ = await prepare(services, local_client, "owner", "local")
    method, path, body = request_for(name, m, owner)
    # admins pass every policy check, so only CSRF can stop them (owner is covered by the matrix)
    admin = make_user(services, "root@x.com", "admin"); login_as(local_client, services, admin, "local")
    headers = {} if bad is None else {"X-CSRF-Token": bad}
    before = (services.mcps.list(), services.scripts.list(m.id))
    r = await local_client.request(method, path, json=body, headers=headers)
    assert (r.status_code, r.json()) == (403, {"error": "csrf"}), name
    assert (services.mcps.list(), services.scripts.list(m.id)) == before
    ev = [e for e in await audit_events(services, "admin.audit") if e["result"] == "denied"]
    assert ev and ev[-1]["target"]["reason"] == "csrf"


async def test_denied_mutation_audited_without_effect(local_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    _, h = await as_user(local_client, services, "d@x.com")
    for method, path, body in (("DELETE", f"/api/mcps/{m.id}", None), ("POST", f"/api/mcps/{m.id}/scripts/start/versions/1/revert", None),
                               ("POST", f"/api/mcps/{m.id}/owner", {"user_id": 1})):
        assert (await local_client.request(method, path, json=body, headers=h)).status_code == 403
    ev = [(e["action"], e["result"]) for e in await audit_events(services, "admin.audit") if e["result"] == "denied"]
    assert ev == [("delete_mcp", "denied"), ("edit_scripts", "denied"), ("transfer_ownership", "denied")]
    assert services.mcps.get(m.id).owner_id == owner.id and services.scripts.get(m.id, "start").version == 1
