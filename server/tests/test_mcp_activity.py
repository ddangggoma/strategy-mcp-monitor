from datetime import timedelta

from app.clock import to_kst_iso
from app.monitor.history import ActionRecord, TransitionRecord
from app.monitor.models import Issue, McpState
from tests.fakes import ok_result
from tests.mcp_helpers import login_as, make_user, seed_mcp


async def test_activity_merges_mcps_newest_first(external_client, services):
    owner = make_user(services, "o@x.com"); csrf = login_as(external_client, services, owner, "external")
    a = seed_mcp(services, owner); b = seed_mcp(services, owner, name="clock", port=9103)
    for m in (a, b):
        r = await external_client.post(f"/api/mcps/{m.id}/actions/start", headers={"X-CSRF-Token": csrf})
        assert r.status_code == 202
        await services.monitor.wait_idle(); services.clock.advance(1)
    body = (await external_client.get("/api/mcp-activity", params={"limit": 10})).json()
    assert [x["name"] for x in body["actions"]] == ["clock", "calc"]
    assert [x["mcp_id"] for x in body["actions"]] == [b.id, a.id]
    assert body["actions"][0]["actor"] == {"id": owner.id, "email": "o@x.com", "name": "o"}
    assert {"id", "run_id", "at", "requested", "kind", "trigger", "reason", "actor_id", "actor", "status",
            "exit_code", "duration_ms", "killed", "error", "mcp_id", "name"} == set(body["actions"][0])


async def test_activity_transition_shape(external_client, services):
    owner = make_user(services, "o@x.com"); login_as(external_client, services, owner, "external")
    m = seed_mcp(services, owner); at = services.clock.now()
    services.history.record_transition(m.id, TransitionRecord(at, McpState.HEALTHY, McpState.SUSPECT, Issue.PROCESS_DOWN))
    t = (await external_client.get("/api/mcp-activity")).json()["transitions"][0]
    assert t == {"mcp_id": m.id, "name": "calc", "at": to_kst_iso(at), "from": "HEALTHY", "to": "SUSPECT", "issue": "PROCESS_DOWN"}


async def test_activity_limit_and_order_across_mcps(external_client, services):
    owner = make_user(services, "o@x.com"); login_as(external_client, services, owner, "external")
    a = seed_mcp(services, owner); b = seed_mcp(services, owner, name="clock", port=9103)
    t0 = services.clock.now()
    # three transitions (a, b, a) at increasing times, plus two at the same instant (later insert first)
    for i, m in enumerate((a, b, a)):
        services.history.record_transition(
            m.id, TransitionRecord(t0 + timedelta(seconds=i), McpState.HEALTHY, McpState.SUSPECT, Issue.UNRESPONSIVE))
    services.history.record_transition(a.id, TransitionRecord(t0 + timedelta(seconds=9), McpState.SUSPECT, McpState.HEALTHY, None))
    services.history.record_transition(b.id, TransitionRecord(t0 + timedelta(seconds=9), McpState.SUSPECT, McpState.HEALTHY, None))
    body = (await external_client.get("/api/mcp-activity", params={"limit": 3})).json()
    assert [(t["mcp_id"], t["to"], t["issue"]) for t in body["transitions"]] == [
        (b.id, "HEALTHY", None), (a.id, "HEALTHY", None), (a.id, "SUSPECT", "UNRESPONSIVE")]
    assert body["actions"] == []


async def test_activity_action_without_actor_and_equal_times(external_client, services):
    owner = make_user(services, "o@x.com"); login_as(external_client, services, owner, "external")
    m = seed_mcp(services, owner); at = services.clock.now()
    for run in ("r1", "r2"):
        services.history.record_action(ActionRecord(run, m.id, at, "restart", "start", "auto", "PROCESS_DOWN", None, ok_result()))
    acts = (await external_client.get("/api/mcp-activity")).json()["actions"]
    assert [a["run_id"] for a in acts] == ["r2", "r1"]  # same instant: later id first
    assert acts[0]["actor"] is None and acts[0]["actor_id"] is None and acts[0]["trigger"] == "auto"


async def test_activity_requires_login(external_client):
    assert (await external_client.get("/api/mcp-activity")).status_code == 401


async def test_activity_on_local_channel_too(local_client, services):
    owner = make_user(services, "o@x.com"); login_as(local_client, services, owner, "local")
    m = seed_mcp(services, owner)
    services.history.record_transition(m.id, TransitionRecord(services.clock.now(), McpState.HEALTHY, McpState.SUSPECT, None))
    body = (await local_client.get("/api/mcp-activity")).json()
    assert [t["mcp_id"] for t in body["transitions"]] == [m.id]


async def test_activity_limit_validation(external_client, services):
    login_as(external_client, services, make_user(services, "d@x.com"), "external")
    assert (await external_client.get("/api/mcp-activity", params={"limit": 0})).status_code == 422
    assert (await external_client.get("/api/mcp-activity", params={"limit": 201})).status_code == 422
    assert (await external_client.get("/api/mcp-activity", params={"limit": 200})).status_code == 200
    assert (await external_client.get("/api/mcp-activity", params={"limit": 1})).status_code == 200
