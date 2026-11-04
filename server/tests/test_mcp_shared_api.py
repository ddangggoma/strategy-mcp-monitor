import asyncio
import json
from datetime import timedelta

import httpx
import pytest

from app.clock import to_kst_iso
from app.monitor.history import ActionRecord
from app.monitor.models import Issue
from app.web import mcp_shared
from app.web.app_factory import create_app
from app.web.deps import SESSION_COOKIE
from app.web.mcp_shared import board_stream
from tests.fakes import ok_result
from tests.live import live_app
from tests.mcp_helpers import login_as, make_user, seed_mcp
from tests.test_auth_api import audit_events

KEYS = {"id", "name", "state", "issue", "latency_ms", "sparkline", "uptime_24h", "last_check_at", "action_due_at", "action_in_sec", "maintenance", "running"}


def parse(chunk: str):
    name = chunk.split("\n", 1)[0].removeprefix("event: ")
    return name, json.loads(chunk.split("data: ", 1)[1])


async def drain(gen, wait=0.3):
    """Everything the generator yields within ``wait`` seconds of quiet."""
    out = []
    while True:
        try:
            out.append(await asyncio.wait_for(anext(gen), wait))
        except TimeoutError:
            return out


async def test_board_anonymous(external_client, services):
    seed_mcp(services, make_user(services, "o@x.com"))
    item = (await external_client.get("/api/board")).json()["mcps"][0]
    assert set(item) == KEYS and item["state"] == "HEALTHY" and item["running"] is None


async def test_board_has_no_endpoint_or_owner(external_client, services):
    seed_mcp(services, make_user(services, "o@x.com"))
    body = (await external_client.get("/api/board")).json()
    assert set(body) == {"now", "mcps"}
    text = json.dumps(body)
    for leaked in ("127.0.0.1", "9102", "o@x.com", "owner", "host", "port"):
        assert leaked not in text


async def test_board_suspect_countdown(external_client, services):
    m = seed_mcp(services, make_user(services, "o@x.com")); t0 = services.clock.now()
    services.monitor._prober.set_check(m.id, Issue.PROCESS_DOWN)
    await services.monitor.issue_round(); await services.monitor.wait_idle(); services.clock.advance(10)
    item = (await external_client.get("/api/board")).json()["mcps"][0]
    assert (item["state"], item["issue"], item["action_in_sec"]) == ("SUSPECT", "PROCESS_DOWN", 20.0)
    assert item["action_due_at"] == to_kst_iso(t0 + timedelta(seconds=30))


async def test_detail_requires_login(external_client, services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    for path in ("/api/mcps", f"/api/mcps/{m.id}", f"/api/mcps/{m.id}/history"):
        assert (await external_client.get(path)).status_code == 401


async def test_detail_and_history(external_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner); login_as(external_client, services, owner, "external")
    d = (await external_client.get(f"/api/mcps/{m.id}")).json()
    assert d["host"] == "127.0.0.1" and d["owner"]["id"] == owner.id and set(d["live"]) == KEYS
    h = (await external_client.get(f"/api/mcps/{m.id}/history?hours=24")).json()
    assert set(h) == {"buckets", "transitions", "actions"}
    for bad in (0, 169):
        assert (await external_client.get(f"/api/mcps/{m.id}/history?hours={bad}")).status_code == 422
    assert (await external_client.get("/api/mcps/999")).json() == {"error": "not_found"}


async def test_detail_shape_and_list(external_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner); login_as(external_client, services, owner, "external")
    d = (await external_client.get(f"/api/mcps/{m.id}")).json()
    assert d["owner"] == {"id": owner.id, "email": "o@x.com", "name": "o"}
    assert d["id"] == m.id and d["created_at"] == to_kst_iso(m.created_at)
    assert {"name", "host", "port", "path", "probe", "action_delay_sec", "script_timeout_sec", "maintenance"} <= set(d)
    assert [x["id"] for x in (await external_client.get("/api/mcps")).json()] == [m.id]
    services.users.set_active(owner.id, False)  # an inactive owner is no longer the effective owner
    other = make_user(services, "d@x.com"); login_as(external_client, services, other, "external")
    assert (await external_client.get(f"/api/mcps/{m.id}")).json()["owner"] is None


async def test_history_content_and_action_detail(external_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner); login_as(external_client, services, owner, "external")
    other = seed_mcp(services, owner, name="clock", port=9103)
    services.history.record(m.id, services.clock.now(), True, 12.0)
    services.history.record(m.id, services.clock.now(), False, None)
    old = services.clock.now() - timedelta(hours=30)
    aid = services.history.record_action(ActionRecord("r1", m.id, services.clock.now(), "restart", "start", "auto", "PROCESS_DOWN", None, ok_result(stdout="out", stderr="err", stdout_truncated=True)))
    services.history.record_action(ActionRecord("r0", m.id, old, "stop", "stop", "manual", "manual", owner.id, ok_result()))
    h = (await external_client.get(f"/api/mcps/{m.id}/history?hours=24")).json()
    assert h["buckets"] == [{"minute": to_kst_iso(services.clock.now().replace(second=0, microsecond=0)), "ok": 1, "total": 2, "avg_latency_ms": 12.0, "max_latency_ms": 12.0}]
    assert [a["run_id"] for a in h["actions"]] == ["r1"]  # the 30 h old one is outside the window
    assert set(h["actions"][0]) == {"id", "run_id", "at", "requested", "kind", "trigger", "reason", "actor_id", "status", "exit_code", "duration_ms", "killed", "error"}
    assert "stdout" not in h["actions"][0]
    d = (await external_client.get(f"/api/mcps/{m.id}/actions/{aid}")).json()
    assert (d["stdout"], d["stderr"], d["stdout_truncated"], d["stderr_truncated"]) == ("out", "err", True, False)
    assert d["requested"] == "restart" and d["kind"] == "start" and d["trigger"] == "auto"
    assert (await external_client.get(f"/api/mcps/{other.id}/actions/{aid}")).json() == {"error": "not_found"}
    assert (await external_client.get(f"/api/mcps/{m.id}/actions/{aid + 99}")).status_code == 404
    assert (await external_client.get(f"/api/mcps/{m.id}/actions/0")).status_code == 422


async def test_transitions_in_history(external_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner); login_as(external_client, services, owner, "external")
    services.monitor._prober.set_check(m.id, Issue.PROCESS_DOWN)
    await services.monitor.issue_round(); await services.monitor.wait_idle()
    t = (await external_client.get(f"/api/mcps/{m.id}/history")).json()["transitions"]
    assert t == [{"at": to_kst_iso(services.clock.now()), "from": "HEALTHY", "to": "SUSPECT", "issue": "PROCESS_DOWN"}]


async def test_put_settings_external(external_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    other = make_user(services, "d@x.com"); csrf = login_as(external_client, services, other, "external"); h = {"X-CSRF-Token": csrf}
    r = await external_client.put(f"/api/mcps/{m.id}", json={"action_delay_sec": 5}, headers=h)
    assert r.status_code == 200 and services.mcps.get(m.id).config.action_delay_sec == 5
    assert r.json()["action_delay_sec"] == 5 and r.json()["owner"]["id"] == owner.id
    assert services.monitor.engine(m.id).config.action_delay_sec == 5
    ev = [e for e in await audit_events(services, "admin.audit") if e["action"] == "mcp_update"]
    assert ev[-1]["result"] == "ok" and ev[-1]["target"]["changes"] == {"action_delay_sec": [30, 5]}
    for bad in ({"port": 0}, {"bogus": 1}):
        r = await external_client.put(f"/api/mcps/{m.id}", json=bad, headers=h)
        assert r.status_code == 422 and r.json() == {"error": "validation"}
    seed_mcp(services, owner, name="clock", port=9103)
    assert (await external_client.put(f"/api/mcps/{m.id}", json={"name": "Clock"}, headers=h)).json() == {"error": "name_taken"}


async def test_put_audit_records_failures_and_skips_noops(external_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner); other = seed_mcp(services, owner, name="clock", port=9103)
    h = {"X-CSRF-Token": login_as(external_client, services, owner, "external")}
    assert (await external_client.put(f"/api/mcps/{m.id}", json={"action_delay_sec": 30}, headers=h)).status_code == 200  # unchanged
    assert (await external_client.put(f"/api/mcps/{m.id}", json={"port": 0}, headers=h)).status_code == 422
    r = await external_client.put(f"/api/mcps/{m.id}", json={"port": other.config.port, "host": other.config.host}, headers=h)
    assert r.status_code == 409 and r.json() == {"error": "endpoint_taken"}
    assert (await external_client.put("/api/mcps/999", json={"action_delay_sec": 5}, headers=h)).json() == {"error": "not_found"}
    assert (await external_client.put(f"/api/mcps/{m.id}", json=[1], headers=h)).status_code == 422
    ev = [(e["result"], e["target"].get("error")) for e in await audit_events(services, "admin.audit") if e["action"] == "mcp_update"]
    assert ev == [("error", "validation"), ("error", "endpoint_taken"), ("error", "not_found")]


async def test_put_maintenance_moves_the_engine(external_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    h = {"X-CSRF-Token": login_as(external_client, services, owner, "external")}
    await external_client.put(f"/api/mcps/{m.id}", json={"maintenance": True}, headers=h)
    assert (await external_client.get("/api/board")).json()["mcps"][0]["state"] == "MAINTENANCE"
    await external_client.put(f"/api/mcps/{m.id}", json={"maintenance": False}, headers=h)
    assert (await external_client.get("/api/board")).json()["mcps"][0]["state"] == "HEALTHY"


async def test_manual_action_flow(external_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    assert (await external_client.post(f"/api/mcps/{m.id}/actions/start")).status_code == 401
    csrf = login_as(external_client, services, owner, "external")
    assert (await external_client.post(f"/api/mcps/{m.id}/actions/start")).json() == {"error": "csrf"}
    h = {"X-CSRF-Token": csrf}; services.monitor._runner.gate = asyncio.Event()
    r = await external_client.post(f"/api/mcps/{m.id}/actions/start", headers=h)
    assert r.status_code == 202 and isinstance(r.json()["run_id"], str)
    assert (await external_client.post(f"/api/mcps/{m.id}/actions/stop", headers=h)).json() == {"error": "action_in_progress"}
    assert (await external_client.post(f"/api/mcps/{m.id}/actions/deploy", headers=h)).status_code == 422
    services.monitor._runner.gate.set(); await services.monitor.wait_idle()
    assert (await external_client.post(f"/api/mcps/{m.id}/actions/stop", headers=h)).status_code == 202
    await services.monitor.wait_idle()
    assert services.mcps.get(m.id).config.maintenance is True


async def test_manual_action_result_audit_and_history(external_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    h = {"X-CSRF-Token": login_as(external_client, services, owner, "external")}
    run_id = (await external_client.post(f"/api/mcps/{m.id}/actions/restart", headers=h)).json()["run_id"]
    await services.monitor.wait_idle()
    acts = (await external_client.get(f"/api/mcps/{m.id}/history")).json()["actions"]
    assert [(a["run_id"], a["trigger"], a["actor_id"], a["status"]) for a in acts][0] == (run_id, "manual", owner.id, "ok")
    ev = [e for e in await audit_events(services, "admin.audit") if e["action"] == "mcp_action"]
    assert [(e["result"], e["target"]) for e in ev] == [("ok", {"mcp_id": m.id, "kind": "restart", "run_id": run_id})]
    services.monitor._runner.gate = asyncio.Event()
    await external_client.post(f"/api/mcps/{m.id}/actions/start", headers=h)
    assert (await external_client.post(f"/api/mcps/{m.id}/actions/start", headers=h)).status_code == 409
    assert (await external_client.post("/api/mcps/999/actions/start", headers=h)).json() == {"error": "not_found"}
    ev = [e for e in await audit_events(services, "admin.audit") if e["action"] == "mcp_action"]
    assert [(e["result"], e["target"].get("error")) for e in ev[1:]] == [("ok", None), ("error", "action_in_progress"), ("error", "not_found")]
    services.monitor._runner.gate.set(); await services.monitor.wait_idle()


# ---- permission matrix ---------------------------------------------------------------


@pytest.mark.parametrize("channel", ["local", "external"])
async def test_permission_matrix(channel, services, local_client, external_client):
    client = local_client if channel == "local" else external_client
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    aid = services.history.record_action(ActionRecord("r1", m.id, services.clock.now(), "start", "start", "auto", "x", None, ok_result()))
    users = {"developer": make_user(services, "d@x.com"), "admin": make_user(services, "a@x.com", "admin")}
    reads = ["/api/mcps", f"/api/mcps/{m.id}", f"/api/mcps/{m.id}/history", f"/api/mcps/{m.id}/actions/{aid}"]
    for role in (None, "developer", "admin"):
        client.cookies.clear()
        csrf = login_as(client, services, users[role], channel) if role else None
        h = {"X-CSRF-Token": csrf} if csrf else {}
        assert (await client.get("/api/board")).status_code == 200  # everyone, both channels
        for path in reads:
            assert (await client.get(path)).status_code == (200 if role else 401), (channel, role, path)
        put = await client.put(f"/api/mcps/{m.id}", json={"action_delay_sec": 11}, headers=h)
        post = await client.post(f"/api/mcps/{m.id}/actions/start", headers=h)
        assert (put.status_code, post.status_code) == ((200, 202) if role else (401, 401)), (channel, role)
        await services.monitor.wait_idle()
        if role:  # a live session without the CSRF token is refused on both unsafe routes
            assert (await client.put(f"/api/mcps/{m.id}", json={"action_delay_sec": 12})).json() == {"error": "csrf"}
            assert (await client.post(f"/api/mcps/{m.id}/actions/start")).json() == {"error": "csrf"}
    assert services.mcps.get(m.id).config.action_delay_sec == 11


@pytest.mark.parametrize("channel", ["local", "external"])
async def test_stream_permission_passes_for_everyone(channel, services, local_client, external_client, monkeypatch):
    """/api/stream needs only VIEW_BOARD: with the stream cap at zero every caller gets 503, never 401/403."""
    client = local_client if channel == "local" else external_client
    monkeypatch.setattr(services.bus, "_max_streams", 0)
    users = {"developer": make_user(services, "d@x.com"), "admin": make_user(services, "a@x.com", "admin")}
    for role in (None, "developer", "admin"):
        client.cookies.clear()
        if role:
            login_as(client, services, users[role], channel)
        r = await client.get("/api/stream")
        assert (r.status_code, r.json()) == (503, {"error": "too_many_streams"})


# ---- SSE -----------------------------------------------------------------------------


async def test_stream_generator(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    sub = services.bus.subscribe()
    gen = board_stream(services.monitor, services.bus, sub, coalesce_sec=0.05, heartbeat_sec=0.3)
    first = await anext(gen)
    assert first.startswith("event: board\n") and json.loads(first.split("data: ", 1)[1])["mcps"][0]["id"] == m.id
    for _ in range(3): services.bus.mark_dirty(m.id)
    nxt = await asyncio.wait_for(anext(gen), 1)
    assert nxt.startswith("event: mcp\n") and json.loads(nxt.split("data: ", 1)[1])["id"] == m.id
    assert await asyncio.wait_for(anext(gen), 1) == ": ping\n\n"
    services.monitor.remove(m.id)
    assert (await asyncio.wait_for(anext(gen), 1)).startswith("event: mcp_removed\n")
    await gen.aclose(); assert services.bus.subscriber_count == 0


async def test_stream_wire_format_and_coalescing(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    sub = services.bus.subscribe(authed=True)
    gen = board_stream(services.monitor, services.bus, sub, coalesce_sec=0.2, heartbeat_sec=5)
    first = await anext(gen)
    assert first.endswith("\n\n") and first.count("\n") == 3 and " " not in first.split("data: ", 1)[1]  # compact JSON, one data line
    assert parse(first)[1]["now"].endswith("+09:00")
    services.bus.mark_dirty(m.id); services.bus.mark_dirty(m.id)
    services.bus.publish("action", {"run_id": "r", "mcp_id": m.id}, public=False)
    t0 = asyncio.get_running_loop().time()
    got = [parse(await asyncio.wait_for(anext(gen), 1)) for _ in range(2)]
    assert asyncio.get_running_loop().time() - t0 >= 0.15  # held back until coalesce_sec after the last send
    assert [n for n, _ in got] == ["mcp", "action"] and got[1][1] == {"run_id": "r", "mcp_id": m.id}
    assert await drain(gen) == []  # the two dirty marks collapsed into one event
    await gen.aclose()


async def test_stream_hides_action_events_from_anonymous(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    anon, authed = services.bus.subscribe(authed=False), services.bus.subscribe(authed=True)
    ga = board_stream(services.monitor, services.bus, anon, coalesce_sec=0.01, heartbeat_sec=5)
    gb = board_stream(services.monitor, services.bus, authed, coalesce_sec=0.01, heartbeat_sec=5)
    await anext(ga); await anext(gb)
    # a real manual action: its action event carries run_id / exit code / duration
    run_id = services.monitor.manual_action(m.id, "start", make_user(services, "d@x.com"))
    await services.monitor.wait_idle()
    anon_out, authed_out = [parse(c) for c in await drain(ga)], [parse(c) for c in await drain(gb)]
    assert "action" not in [n for n, _ in anon_out] and run_id not in json.dumps(anon_out)
    assert "exit_code" not in json.dumps(anon_out) and "duration_ms" not in json.dumps(anon_out)
    assert [n for n, _ in anon_out] and {n for n, _ in anon_out} <= {"mcp"}  # still gets state changes
    action = next(d for n, d in authed_out if n == "action")
    assert (action["run_id"], action["mcp_id"], action["kind"], action["status"], action["exit_code"]) == (run_id, m.id, "start", "ok", 0)
    await ga.aclose(); await gb.aclose()


async def test_stream_not_registered_until_first_iteration(services):
    """The route's generator subscribes on its first step and a never-started one holds no slot."""
    request_gen = mcp_shared.open_stream(services, authed=False, ip="9.9.9.9")
    assert services.bus.subscriber_count == 0
    await request_gen.aclose()
    assert services.bus.subscriber_count == 0
    gen = mcp_shared.open_stream(services, authed=False, ip="9.9.9.9")
    assert (await anext(gen)).startswith("event: board\n") and services.bus.subscriber_count == 1
    await gen.aclose()
    assert services.bus.subscriber_count == 0
    gen = mcp_shared.open_stream(services, authed=False, ip="9.9.9.9")
    await anext(gen)
    with pytest.raises(asyncio.CancelledError):
        task = asyncio.ensure_future(anext(gen)); await asyncio.sleep(0.05); task.cancel(); await task
    await gen.aclose()
    assert services.bus.subscriber_count == 0


async def test_stream_over_http(services):
    async with live_app(create_app("external", services)) as base, httpx.AsyncClient() as c:
        async with c.stream("GET", base + "/api/stream") as r:
            assert r.headers["content-type"].startswith("text/event-stream") and r.headers["cache-control"] == "no-store"
            assert (await anext(r.aiter_lines())) == "event: board"


async def test_stream_headers_exact(services):
    async with live_app(create_app("external", services)) as base, httpx.AsyncClient() as c:
        async with c.stream("GET", base + "/api/stream") as r:
            assert r.headers["content-type"] == "text/event-stream; charset=utf-8"
            assert (r.headers["cache-control"], r.headers["x-accel-buffering"]) == ("no-store", "no")


async def wait_for_count(bus, n, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while bus.subscriber_count != n:
        assert asyncio.get_running_loop().time() < deadline, f"subscriber_count stuck at {bus.subscriber_count}"
        await asyncio.sleep(0.02)


async def test_stream_releases_slot_on_disconnect(services):
    async with live_app(create_app("external", services)) as base, httpx.AsyncClient() as c:
        for _ in range(8):  # more than the per-IP cap: a leak would show as a 429
            async with c.stream("GET", base + "/api/stream") as r:
                assert r.status_code == 200
                assert (await anext(r.aiter_lines())) == "event: board"
                assert services.bus.subscriber_count == 1
            await wait_for_count(services.bus, 0)


async def test_stream_delivers_events_over_http(services, monkeypatch):
    monkeypatch.setattr(mcp_shared, "COALESCE_SEC", 0.05)
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    sid, _ = services.sessions.create(owner.id, "external", "127.0.0.1", "ua")
    async with live_app(create_app("external", services)) as base, httpx.AsyncClient() as c:
        async with c.stream("GET", base + "/api/stream", headers={"Cookie": f"{SESSION_COOKIE}={sid}"}) as r:
            lines = r.aiter_lines()

            async def event():
                name = None
                async for line in lines:
                    if line.startswith("event: "): name = line[7:]
                    elif line.startswith("data: "): return name, json.loads(line[6:])

            assert (await event())[0] == "board"
            services.monitor.manual_action(m.id, "stop", owner)
            seen = []
            while "action" not in seen:
                seen.append((await asyncio.wait_for(event(), 5))[0])
            assert "mcp" in seen


async def test_anonymous_stream_over_http_never_sees_actions(services, monkeypatch):
    monkeypatch.setattr(mcp_shared, "COALESCE_SEC", 0.05)
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    async with live_app(create_app("external", services)) as base, httpx.AsyncClient() as c:
        async with c.stream("GET", base + "/api/stream") as r:
            lines = r.aiter_lines()
            assert await anext(lines) == "event: board"
            run_id = services.monitor.manual_action(m.id, "start", owner)
            await services.monitor.wait_idle()
            services.bus.publish("sentinel", {})  # public: arrives after anything queued before it
            names = []
            async for line in lines:
                assert run_id not in line and "exit_code" not in line
                if line.startswith("event: "):
                    names.append(line[7:])
                    if names[-1] == "sentinel":
                        break
            assert "action" not in names and names[0] == "mcp"


async def test_stream_limit_503(external_client, services, monkeypatch):
    monkeypatch.setattr(services.bus, "_max_streams", 0)
    r = await external_client.get("/api/stream")
    assert r.status_code == 503 and r.json() == {"error": "too_many_streams"}


async def test_stream_per_ip_limit_429(external_client, services):
    for _ in range(5):
        services.bus.subscribe(ip="127.0.0.1")  # the test client's address
    r = await external_client.get("/api/stream")
    assert r.status_code == 429 and r.json() == {"error": "rate_limited"} and "retry-after" in r.headers
    assert services.bus.subscriber_count == 5  # a refused request holds nothing


async def test_stream_per_ip_limit_over_http_frees_on_close(services):
    async with live_app(create_app("external", services)) as base, httpx.AsyncClient() as c:
        opened = []
        for _ in range(5):
            cm = c.stream("GET", base + "/api/stream"); r = await cm.__aenter__(); lines = r.aiter_lines(); opened.append((cm, lines))  # keep `lines`: dropping it closes the stream
            assert (await anext(lines)) == "event: board"
        assert services.bus.subscriber_count == 5
        async with c.stream("GET", base + "/api/stream") as sixth:
            assert (sixth.status_code, (await sixth.aread())) == (429, b'{"error":"rate_limited"}')
        cm, _r = opened.pop()
        await cm.__aexit__(None, None, None)
        await wait_for_count(services.bus, 4)
        async with c.stream("GET", base + "/api/stream") as again:
            assert again.status_code == 200 and (await anext(again.aiter_lines())) == "event: board"
        for cm, _r in opened:
            await cm.__aexit__(None, None, None)
        await wait_for_count(services.bus, 0)
