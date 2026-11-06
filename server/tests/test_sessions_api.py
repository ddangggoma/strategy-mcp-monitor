import asyncio
from datetime import timedelta

import pytest

from app.clock import to_kst_iso
from app.sessions.history import LogonFailureIn
from app.web.mcp_shared import board_snapshot, board_stream
from tests.mcp_helpers import login_as, make_user
from tests.session_helpers import snap, ws

CONNECTION_KEYS = {"id", "session_id", "user", "domain", "client_name", "client_ip", "reverse_dns", "client_build",
                   "protocol", "resolution", "kind", "logon_at", "connected_at", "ended_at", "end_reason",
                   "first_seen_ip", "first_seen_device", "notice"}
FAILURE_KEYS = {"id", "at", "user", "domain", "client_ip", "workstation", "logon_type", "status", "sub_status",
                "source"}


async def test_board_has_no_sessions_until_first_snapshot(external_client):
    assert "sessions" not in (await external_client.get("/api/board")).json()


async def test_anonymous_board_and_stream_carry_sessions(external_client, services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    b = (await external_client.get("/api/board")).json()
    assert (b["sessions"][0]["client_ip"], b["sessions"][0]["user"]) == ("10.0.3.21", "hong")
    sub = services.bus.subscribe(authed=False)
    gen = board_stream(services.monitor, services.bus, sub, snapshot=lambda: board_snapshot(services),
                       coalesce_sec=0.01, heartbeat_sec=5)
    try:
        first = await anext(gen)
        assert first.startswith("event: board\n") and '"sessions":[{' in first
        services.rdp.apply(snap(clock.now()))  # logoff
        assert await asyncio.wait_for(anext(gen), 2) == 'event: sessions\ndata: {"sessions":[]}\n\n'
    finally:
        await gen.aclose()


async def test_history_requires_login_and_paginates(external_client, services, clock):
    assert (await external_client.get("/api/sessions/history")).status_code == 401
    login_as(external_client, services, make_user(services, "d@x.com"), "external")
    t = services.rdp; t.apply(snap(clock.now()))
    for _ in range(3):
        clock.advance(10); t.apply(snap(clock.now(), ws(2, logon=clock.now(), connected=clock.now())))
        clock.advance(10); t.apply(snap(clock.now()))
    r1 = (await external_client.get("/api/sessions/history", params={"limit": 2})).json()
    assert len(r1["connections"]) == 2 and r1["next_before_id"] == r1["connections"][-1]["id"]
    c = r1["connections"][0]
    assert set(c) == CONNECTION_KEYS and (c["kind"], c["end_reason"], c["notice"]["closed_reason"]) == ("logon", "logoff", "logoff")
    assert c["connected_at"] == to_kst_iso(services.rdp_history.get(c["id"]).connected_at)
    r2 = (await external_client.get("/api/sessions/history", params={"limit": 2, "before_id": r1["next_before_id"]})).json()
    assert len(r2["connections"]) == 1 and r2["next_before_id"] is None and r2["failures"] == []
    assert (await external_client.get("/api/sessions/history", params={"days": 91})).status_code == 422


async def test_current_lists_disconnected_sessions(external_client, services, clock):
    login_as(external_client, services, make_user(services, "d@x.com"), "external")
    services.rdp.apply(snap(clock.now(), ws(2), ws(3, state="disconnected", user="kim")))
    body = (await external_client.get("/api/sessions/current")).json()
    assert body["ready"] is True
    assert sorted((s["session_id"], s["state"]) for s in body["sessions"]) == [(2, "active"), (3, "disconnected")]


async def test_collectors_status(external_client, services, clock):
    login_as(external_client, services, make_user(services, "d@x.com"), "external")
    services.collectors.report("wts", False, "access denied")
    assert (await external_client.get("/api/sessions/collectors")).json() == \
        [{"name": "wts", "ok": False, "error": "access denied", "since": to_kst_iso(clock.now())}]


# ---- beyond the plan's list ---------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/sessions/current", "/api/sessions/history", "/api/sessions/collectors"])
async def test_session_routes_on_both_channels_need_a_login(local_client, external_client, services, path):
    for client in (external_client, local_client):
        r = await client.get(path)
        assert r.status_code == 401 and r.json() == {"error": "login_required"}
    login_as(local_client, services, make_user(services, "d@x.com"), "local")
    assert (await local_client.get(path)).status_code == 200


async def test_current_before_the_first_snapshot(external_client, services):
    login_as(external_client, services, make_user(services, "d@x.com"), "external")
    assert (await external_client.get("/api/sessions/current")).json() == {"ready": False, "sessions": []}
    assert (await external_client.get("/api/sessions/collectors")).json() == []


@pytest.mark.parametrize("params", [{"days": 0}, {"limit": 0}, {"limit": 501}, {"before_id": 0},
                                    {"before_id": 2**63}, {"days": "x"}])
async def test_history_rejects_out_of_range_params(external_client, services, params):
    login_as(external_client, services, make_user(services, "d@x.com"), "external")
    r = await external_client.get("/api/sessions/history", params=params)
    assert r.status_code == 422 and r.json() == {"error": "validation"}


async def test_history_days_window_and_failures(external_client, services, clock):
    h = services.rdp_history
    old = h.open(ws(2), "logon", clock.now()); h.close(old.id, clock.now(), "logoff")
    h.add_failure(LogonFailureIn(at=clock.now(), user="kim", domain="CORP", client_ip="203.0.113.9",
                                 workstation="X", logon_type=10, status="0xc000006d", sub_status="0xc000006a",
                                 source="eventlog:4625", record_id=7))
    clock.advance(2 * 86400)
    new = h.open(ws(3, ip="10.0.3.22", connected=clock.now()), "reconnect", clock.now())
    login_as(external_client, services, make_user(services, "d@x.com"), "external")  # after the clock jump
    body = (await external_client.get("/api/sessions/history", params={"days": 1})).json()
    assert [c["id"] for c in body["connections"]] == [new.id] and body["failures"] == []
    body = (await external_client.get("/api/sessions/history", params={"days": 3})).json()
    assert [c["id"] for c in body["connections"]] == [new.id, old.id] and body["next_before_id"] is None
    assert body["connections"][0]["ended_at"] is None and body["connections"][0]["first_seen_ip"] is True
    [f] = body["failures"]
    assert set(f) == FAILURE_KEYS and (f["user"], f["status"], f["logon_type"]) == ("kim", "0xc000006d", 10)
    assert f["at"] == to_kst_iso(clock.now() - timedelta(days=2))
    # Failures are not paged by the connection cursor: only the first page carries them.
    paged = (await external_client.get("/api/sessions/history", params={"days": 3, "before_id": new.id})).json()
    assert [c["id"] for c in paged["connections"]] == [old.id] and paged["failures"] == []


async def test_stream_without_sessions_until_ready(services):
    sub = services.bus.subscribe(authed=False)
    gen = board_stream(services.monitor, services.bus, sub, snapshot=lambda: board_snapshot(services),
                       coalesce_sec=0.01, heartbeat_sec=5)
    try:
        first = await anext(gen)
        assert first.startswith("event: board\n") and '"sessions"' not in first
    finally:
        await gen.aclose()
