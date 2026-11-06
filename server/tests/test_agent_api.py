import asyncio
import json
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.activity.agent_hub import HELLO, AgentAuthError
from app.clock import to_kst_iso
from app.collect.config import CollectorConfig
from app.services import build_services
from app.win.peer import PeerInfo
from tests.fakes import CapturingOtpProvider, FakeProber, FakeRunner
from tests.session_helpers import T0, snap, ws
from tests.test_auth_api import audit_events
from tests.winfakes import FakePeerResolver

AGENT2 = PeerInfo(500, 2, "CORP\\hong", r"C:\Python315\python.exe")
FIX = Path(__file__).parent / "fixtures" / "agent-events.json"

def H(token):
    return {"X-Agent-Token": token}

@pytest.fixture
def agent(services, clock):
    services.peers = FakePeerResolver(AGENT2)
    services.agents.reshow_delay_sec = 0.01
    services.rdp.apply(snap(clock.now(), ws(2)))
    return services.agents.mint(2, "hong")

async def hello(client, token):
    r = await client.post("/api/agent/hello", json={"session_id": 2, "pid": 500, "version": "0.1.0"}, headers=H(token))
    assert r.status_code == 200
    return r.json()

def token_of(url):
    return parse_qs(urlsplit(url).fragment)["t"][0]

async def test_hello_then_next_delivers_pending_notice(local_client, services, agent):
    assert await hello(local_client, agent) == {"heartbeat_sec": 5, "events_max": 200, "idle_threshold_sec": 300,
                                                "window_events": True}
    cmd = (await local_client.get("/api/agent/next", params={"timeout": 0}, headers=H(agent))).json()
    d = services.displays.pending_for_session(2)
    assert (cmd["type"], cmd["display_id"], cmd["attempt"]) == ("show_notice", d.id, 1)
    assert cmd["url"].startswith(f"http://127.0.0.1:8700/notice#d={d.id}&t=")
    assert (await local_client.get("/api/agent/next", params={"timeout": 0.05}, headers=H(agent))).status_code == 204

async def test_ack_queues_close_notice(local_client, services, agent):
    await hello(local_client, agent)
    cmd = (await local_client.get("/api/agent/next", params={"timeout": 0}, headers=H(agent))).json()
    assert (await local_client.post("/api/notice/display/ack", headers={"X-Notice-Token": token_of(cmd["url"])})).status_code == 204
    nxt = (await local_client.get("/api/agent/next", params={"timeout": 1}, headers=H(agent))).json()
    assert nxt == {"type": "close_notice", "display_id": cmd["display_id"]}

async def test_token_used_from_another_session_is_rejected_and_reported(local_client, services, agent):
    services.peers = FakePeerResolver(PeerInfo(900, 3, "CORP\\kim", r"C:\Python315\python.exe"))
    r = await local_client.post("/api/agent/heartbeat", json={"idle_sec": 0, "locked": False}, headers=H(agent))
    assert (r.status_code, r.json()) == (403, {"error": "forbidden"})
    rec = services.tamper.recent(1)[0]
    assert (rec["event"], rec["claimed_session"], rec["peer_session"], rec["peer_pid"]) == ("agent_impersonation", 2, 3, 900)

async def test_missing_or_unknown_token_is_401_without_tamper(local_client, services, agent):
    for headers in ({}, H("nope")):
        r = await local_client.post("/api/agent/heartbeat", json={"idle_sec": 0, "locked": None}, headers=headers)
        assert (r.status_code, r.json()) == (401, {"error": "login_required"})
    assert services.tamper.recent() == []

async def test_hello_with_wrong_session_id_is_403(local_client, services, agent):
    r = await local_client.post("/api/agent/hello", json={"session_id": 3, "pid": 500, "version": "0.1.0"}, headers=H(agent))
    assert r.status_code == 403 and services.tamper.recent(1)[0]["event"] == "agent_impersonation"

async def test_events_are_logged_with_session_context_and_event_time(local_client, services, agent):
    await hello(local_client, agent)
    body = json.loads(FIX.read_text("utf-8"))
    assert (await local_client.post("/api/agent/events", json=body, headers=H(agent))).status_code == 204
    w = await audit_events(services, "activity.window"); i = await audit_events(services, "activity.idle")
    assert [e["event"] for e in w] == ["foreground", "title", "minimize"]
    assert (w[0]["ts"], w[0]["title"], w[0]["session_id"], w[0]["client_ip"], w[0]["user"], w[0]["source"]) == \
        ("2026-11-04T13:59:57.000+09:00", "메모 - 메모장", 2, "10.0.3.21", "CORP\\hong", "agent")
    assert (i[0]["event"], i[0]["idle_sec"], "clock_skew" in i[0]) == ("idle", 300, False)

async def test_event_clock_skew_is_clamped(local_client, services, agent, clock):
    await hello(local_client, agent)
    far = (clock.now() - timedelta(hours=2)).isoformat()
    await local_client.post("/api/agent/events", json={"events": [{"type": "idle", "at": far, "idle_sec": 1}]}, headers=H(agent))
    [e] = await audit_events(services, "activity.idle")
    assert (e["ts"], e["clock_skew"]) == (to_kst_iso(clock.now()), True)

async def test_events_validation(local_client, services, agent):
    await hello(local_client, agent)
    one = {"type": "foreground", "at": "2026-11-04T13:59:57+09:00", "pid": 1, "exe": None, "title": "x"}
    for body in ({"events": [one] * 201}, {"events": [{**one, "title": "x" * 513}]}, {"events": [{**one, "at": "2026-11-04T13:59:57"}]}):
        assert (await local_client.post("/api/agent/events", json=body, headers=H(agent))).status_code == 422

async def test_closed_window_logs_unacknowledged_and_reshows(local_client, services, agent):
    await hello(local_client, agent)
    first = (await local_client.get("/api/agent/next", params={"timeout": 0}, headers=H(agent))).json()
    r = await local_client.post(f"/api/agent/notice/{first['display_id']}/closed", headers=H(agent))
    assert r.status_code == 204
    again = (await local_client.get("/api/agent/next", params={"timeout": 1}, headers=H(agent))).json()
    assert (again["type"], again["display_id"], again["attempt"]) == ("show_notice", first["display_id"], 2)
    assert token_of(again["url"]) != token_of(first["url"])
    un = [e for e in await audit_events(services, "notice") if e["event"] == "notice_unacknowledged"]
    assert [e["reason"] for e in un] == ["window_closed"]

async def test_agent_routes_absent_on_external(external_client):
    for method, path in [("POST", "/api/agent/hello"), ("GET", "/api/agent/next"), ("POST", "/api/agent/heartbeat"),
                         ("POST", "/api/agent/events"), ("POST", "/api/agent/notice/1/closed")]:
        assert (await external_client.request(method, path, headers=H("x"))).status_code == 404


# --- beyond the plan's tests -------------------------------------------------------------------

def commands(services, session_id=2):
    return list(services.agents.slot(session_id).commands)

async def test_reconnect_with_a_hello_agent_queues_one_notice_with_attempt_1(local_client, services, agent, clock):
    """F09: the display listener and the supervisor's ensure() both ask to show; one token, attempt 1."""
    await hello(local_client, agent)
    await local_client.get("/api/agent/next", params={"timeout": 0}, headers=H(agent))  # first notice delivered
    clock.advance(30)
    services.rdp.apply(snap(clock.now(), ws(2, logon=T0, connected=clock.now())))  # fast reconnect
    assert services.agents.show_pending(2) is False  # what AgentSupervisor.ensure does for a live agent
    d = services.displays.pending_for_session(2)
    [cmd] = commands(services)
    assert (cmd["type"], cmd["display_id"], cmd["attempt"], d.attempts, d.kind) == ("show_notice", d.id, 1, 1, "reconnect")

async def test_show_pending_is_idempotent_until_the_window_is_closed(local_client, services, agent):
    await hello(local_client, agent)
    assert services.agents.show_pending(2) is False
    [cmd] = commands(services)
    assert cmd["attempt"] == 1 and services.displays.pending_for_session(2).attempts == 1

async def test_a_new_show_notice_replaces_a_queued_one_of_a_superseded_display(local_client, services, agent, clock):
    await hello(local_client, agent)  # first notice queued, not fetched
    clock.advance(30)
    services.rdp.apply(snap(clock.now(), ws(2, logon=T0, connected=clock.now())))
    [cmd] = commands(services)
    assert cmd["display_id"] == services.displays.pending_for_session(2).id

async def test_show_pending_waits_for_hello_and_an_open_display(services, agent, clock):
    assert services.agents.show_pending(2) is False and commands(services) == []  # no hello yet
    services.agents.mint(3, "kim")
    assert services.agents.show_pending(3) is False  # no slot hello / no display
    assert services.agents.show_pending(7) is False  # no slot at all

async def test_long_poll_is_woken_by_a_queued_command(local_client, services, agent):
    await hello(local_client, agent)
    await local_client.get("/api/agent/next", params={"timeout": 0}, headers=H(agent))
    task = asyncio.create_task(local_client.get("/api/agent/next", params={"timeout": 5}, headers=H(agent)))
    await asyncio.sleep(0.05)
    services.agents.queue(2, {"type": "exit"})
    r = await asyncio.wait_for(task, 2)
    assert (r.status_code, r.json()) == (200, {"type": "exit"})

async def test_mint_replaces_the_previous_token_and_releases_its_long_poll(local_client, services, agent):
    await hello(local_client, agent)
    await local_client.get("/api/agent/next", params={"timeout": 0}, headers=H(agent))
    task = asyncio.create_task(local_client.get("/api/agent/next", params={"timeout": 5}, headers=H(agent)))
    await asyncio.sleep(0.05)
    new = services.agents.mint(2, "hong")
    r = await asyncio.wait_for(task, 2)
    assert r.status_code == 204
    assert (await local_client.post("/api/agent/heartbeat", json={}, headers=H(agent))).status_code == 401
    assert (await local_client.post("/api/agent/heartbeat", json={}, headers=H(new))).status_code == 204
    services.agents.revoke(2)
    assert services.agents.slot(2) is None
    assert (await local_client.post("/api/agent/heartbeat", json={}, headers=H(new))).status_code == 401

async def test_hello_with_a_pid_other_than_the_peer_is_403(local_client, services, agent):
    r = await local_client.post("/api/agent/hello", json={"session_id": 2, "pid": 501, "version": "0.1.0"}, headers=H(agent))
    assert (r.status_code, r.json()) == (403, {"error": "forbidden"})
    rec = services.tamper.recent(1)[0]
    assert (rec["event"], rec["claimed_session"], rec["peer_session"], rec["peer_pid"], rec["peer_exe"], rec["peer_user"]) == \
        ("agent_impersonation", 2, 2, 500, r"C:\Python315\python.exe", "CORP\\hong")
    assert services.agents.slot(2).hello_at is None

async def test_unresolved_peer_is_503_without_tamper(local_client, services, agent):
    """M2: a resolver miss is not evidence of impersonation; the agent retries a 503."""
    services.peers = FakePeerResolver(None)
    r = await local_client.post("/api/agent/heartbeat", json={}, headers=H(agent))
    assert (r.status_code, r.json()) == (503, {"error": "unavailable"})
    assert len(services.peers.calls) == 3  # looked up again briefly before giving up
    assert services.tamper.recent() == []

class FlakyPeerResolver:
    def __init__(self, misses, info):
        self.misses, self.info, self.calls = misses, info, 0
    def resolve(self, client_ip, client_port, server_port):
        self.calls += 1
        if self.calls <= self.misses:
            return None
        return self.info

async def test_a_peer_resolved_on_retry_is_accepted(local_client, services, agent):
    services.peers = FlakyPeerResolver(1, AGENT2)
    r = await local_client.post("/api/agent/heartbeat", json={}, headers=H(agent))
    assert r.status_code == 204 and services.peers.calls == 2 and services.tamper.recent() == []

async def test_unknown_token_is_refused_before_any_peer_lookup(local_client, services, agent):
    """M1: a garbage token costs no connection-table scan."""
    services.peers = FakePeerResolver(AGENT2)
    for headers in ({}, H("nope")):
        assert (await local_client.post("/api/agent/heartbeat", json={}, headers=headers)).status_code == 401
    assert services.peers.calls == []

async def test_impersonation_is_reported_once_per_minute_with_a_count(local_client, services, agent, clock):
    """M3: a stolen token replayed in a loop does not flood the tamper log, ring and SSE."""
    services.peers = FakePeerResolver(PeerInfo(900, 3, "CORP\\kim", None))
    for _ in range(5):
        assert (await local_client.post("/api/agent/heartbeat", json={}, headers=H(agent))).status_code == 403
    assert [r["event"] for r in services.tamper.recent()] == ["agent_impersonation"]
    clock.advance(61)
    assert (await local_client.post("/api/agent/heartbeat", json={}, headers=H(agent))).status_code == 403
    recs = services.tamper.recent()
    assert [r["event"] for r in recs] == ["agent_impersonation"] * 2 and recs[0]["suppressed"] == 4
    assert "suppressed" not in recs[1]
    lines = [e for e in await audit_events(services, "tamper") if e["event"] == "agent_impersonation"]
    assert len(lines) == 2


# --- I1: the server proves itself to the agent ------------------------------------------------

from app.activity.agent_hub import server_proof  # noqa: E402


def HN(token, nonce):
    return {"X-Agent-Token": token, "X-Agent-Nonce": nonce}

async def test_every_agent_response_proves_the_server_key(local_client, services, agent):
    key = services.agents.slot(2).server_key
    r = await local_client.post("/api/agent/hello", json={"session_id": 2, "pid": 500, "version": "0.1.0"}, headers=HN(agent, "n1"))
    assert r.status_code == 200 and r.headers["X-Server-Proof"] == server_proof(key, "n1")
    r = await local_client.get("/api/agent/next", params={"timeout": 0}, headers=HN(agent, "n2"))
    assert r.status_code == 200 and r.headers["X-Server-Proof"] == server_proof(key, "n2")
    r = await local_client.get("/api/agent/next", params={"timeout": 0}, headers=HN(agent, "n3"))
    assert r.status_code == 204 and r.headers["X-Server-Proof"] == server_proof(key, "n3")
    r = await local_client.post("/api/agent/events", json={"events": "bad"}, headers=HN(agent, "n4"))
    assert r.status_code == 422 and r.headers["X-Server-Proof"] == server_proof(key, "n4")

async def test_no_proof_without_a_live_token_a_nonce_or_on_a_refusal(local_client, services, agent):
    assert "X-Server-Proof" not in (await local_client.post("/api/agent/heartbeat", json={}, headers=HN("nope", "n"))).headers
    assert "X-Server-Proof" not in (await local_client.post("/api/agent/heartbeat", json={}, headers=H(agent))).headers
    assert "X-Server-Proof" not in (await local_client.post("/api/agent/heartbeat", json={}, headers=HN(agent, "n" * 129))).headers
    services.peers = FakePeerResolver(PeerInfo(900, 3, None, None))  # another session: 403, no proof
    r = await local_client.post("/api/agent/heartbeat", json={}, headers=HN(agent, "n"))
    assert r.status_code == 403 and "X-Server-Proof" not in r.headers

def test_server_proof_is_hmac_sha256_of_the_nonce():
    import hashlib
    import hmac
    key = "ab" * 32
    assert server_proof(key, "xyz") == hmac.new(bytes.fromhex(key), b"xyz", hashlib.sha256).hexdigest()

def test_each_mint_has_its_own_server_key(services, agent):
    first = services.agents.slot(2).server_key
    services.agents.mint(2, "hong")
    assert services.agents.slot(2).server_key != first and len(first) == 64

async def test_authenticate_and_hello_record_the_agent(local_client, services, agent, clock):
    clock.advance(4)
    await hello(local_client, agent)
    slot = services.agents.slot(2)
    assert (slot.pid, slot.version, slot.hello_at, slot.last_seen, slot.user) == (500, "0.1.0", clock.now(), clock.now(), "hong")
    clock.advance(5)
    assert (await local_client.post("/api/agent/heartbeat", json={"idle_sec": 12, "locked": True}, headers=H(agent))).status_code == 204
    assert slot.last_seen == clock.now()

def test_authenticate_errors_carry_status_and_code(services, agent):
    with pytest.raises(AgentAuthError) as e:
        services.agents.authenticate(None, AGENT2)
    assert (e.value.status, e.value.code) == (401, "login_required")
    with pytest.raises(AgentAuthError) as e:
        services.agents.authenticate(agent, PeerInfo(500, 3, None, None))
    assert (e.value.status, e.value.code) == (403, "forbidden")
    assert services.agents.authenticate(agent, AGENT2) is services.agents.slot(2)

async def test_closed_for_another_display_is_ignored(local_client, services, agent):
    await hello(local_client, agent)
    await local_client.get("/api/agent/next", params={"timeout": 0}, headers=H(agent))
    assert (await local_client.post("/api/agent/notice/999/closed", headers=H(agent))).status_code == 204
    await asyncio.sleep(0.05)
    assert commands(services) == []
    assert [e for e in await audit_events(services, "notice") if e["event"] == "notice_unacknowledged"] == []

async def test_a_repeated_closed_report_is_logged_and_reshown_once(local_client, services, agent):
    services.agents.reshow_delay_sec = 0.05
    await hello(local_client, agent)
    first = (await local_client.get("/api/agent/next", params={"timeout": 0}, headers=H(agent))).json()
    for _ in range(2):
        await local_client.post(f"/api/agent/notice/{first['display_id']}/closed", headers=H(agent))
    await asyncio.sleep(0.15)
    assert [c["attempt"] for c in commands(services)] == [2]
    un = [e for e in await audit_events(services, "notice") if e["event"] == "notice_unacknowledged"]
    assert [e["reason"] for e in un] == ["window_closed"]

async def test_closed_display_id_is_validated(local_client, services, agent):
    for bad in ("0", "abc", str(2**63)):
        assert (await local_client.post(f"/api/agent/notice/{bad}/closed", headers=H(agent))).status_code == 422

async def test_reshow_after_close_is_skipped_once_acknowledged(local_client, services, agent):
    services.agents.reshow_delay_sec = 0.05
    await hello(local_client, agent)
    first = (await local_client.get("/api/agent/next", params={"timeout": 0}, headers=H(agent))).json()
    await local_client.post(f"/api/agent/notice/{first['display_id']}/closed", headers=H(agent))
    services.displays.acknowledge(token_of(first["url"]), 2)
    await asyncio.sleep(0.1)
    assert commands(services) == [{"type": "close_notice", "display_id": first["display_id"]}]

async def test_ack_drops_a_queued_show_notice_of_that_display(local_client, services, agent):
    await hello(local_client, agent)
    [cmd] = commands(services)
    services.displays.acknowledge(token_of(cmd["url"]), 2)
    assert commands(services) == [{"type": "close_notice", "display_id": cmd["display_id"]}]

async def test_agent_exited_logs_unacknowledged_for_the_open_display(services, agent):
    services.agents.agent_exited(2)
    services.agents.agent_exited(7)  # no display: nothing
    un = [e for e in await audit_events(services, "notice") if e["event"] == "notice_unacknowledged"]
    assert [(e["reason"], e["session_id"]) for e in un] == [("agent_exited", 2)]

async def test_configure_changes_the_notice_url_base(local_client, services, agent):
    services.agents.configure("http://127.0.0.1:18700")
    await hello(local_client, agent)
    [cmd] = commands(services)
    assert cmd["url"].startswith(f"http://127.0.0.1:18700/notice#d={cmd['display_id']}&t=")

async def test_next_timeout_and_body_validation(local_client, services, agent):
    await hello(local_client, agent)
    for t in ("-1", "30.5", "x"):
        assert (await local_client.get("/api/agent/next", params={"timeout": t}, headers=H(agent))).status_code == 422
    bad_bodies = [
        ("/api/agent/hello", {"session_id": 2, "pid": 500, "version": "v" * 41}),
        ("/api/agent/hello", {"session_id": 2, "pid": 0, "version": "0.1.0"}),
        ("/api/agent/hello", {"session_id": 2, "pid": 500, "version": "0.1.0", "extra": 1}),
        ("/api/agent/heartbeat", {"idle_sec": -1, "locked": None}),
        ("/api/agent/heartbeat", {"idle_sec": 0, "locked": None, "x": 1}),
        ("/api/agent/events", {"events": [{"type": "scroll", "at": "2026-11-04T13:59:57+09:00", "idle_sec": 1}]}),
        ("/api/agent/events", {"events": [{"type": "idle", "at": "2026-11-04T13:59:57+09:00", "idle_sec": 1, "pid": 3}]}),
    ]
    for path, body in bad_bodies:
        assert (await local_client.post(path, json=body, headers=H(agent))).status_code == 422, (path, body)

async def test_events_up_to_200_are_accepted(local_client, services, agent):
    await hello(local_client, agent)
    one = {"type": "restore", "at": "2026-11-04T13:59:57+09:00", "pid": 1, "exe": None, "title": "x"}
    assert (await local_client.post("/api/agent/events", json={"events": [one] * 200}, headers=H(agent))).status_code == 204
    assert len(await audit_events(services, "activity.window")) == 200

async def test_activity_off_disables_window_events(tmp_path, clock):
    """F13: --activity off reaches the agent through hello, and /events is ignored."""
    import httpx

    from app.web.app_factory import create_app
    svc = build_services(tmp_path, clock=clock, otp_provider=CapturingOtpProvider(), runner=FakeRunner(),
                         prober=FakeProber(clock), peer_resolver=FakePeerResolver(AGENT2),
                         collectors=CollectorConfig(activity=False))
    await svc.log.start()
    try:
        token = svc.agents.mint(2, "hong")
        transport = httpx.ASGITransport(app=create_app("local", svc))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8700") as client:
            assert (await hello(client, token)) == {**HELLO, "window_events": False}
            r = await client.post("/api/agent/events", json=json.loads(FIX.read_text("utf-8")), headers=H(token))
            assert r.status_code == 204
        await svc.log.flush()
        day = svc.paths.logs_dir / "2026-11-04.jsonl"
        lines = [json.loads(x) for x in day.read_text("utf-8").splitlines()] if day.exists() else []
        assert [e for e in lines if e["cat"].startswith("activity.")] == []
    finally:
        await svc.log.stop()
        svc.db.close()


async def test_a_window_title_with_a_notice_token_is_redacted(local_client, services, agent):
    """I2: an Edge --app window is captioned with its URL until the page title loads."""
    await hello(local_client, agent)
    ev = {"type": "title", "at": "2026-11-04T13:59:57+09:00", "pid": 1, "exe": "msedge.exe",
          "title": "127.0.0.1:8700/notice#d=4&t=SeCrEt-123"}
    assert (await local_client.post("/api/agent/events", json={"events": [ev]}, headers=H(agent))).status_code == 204
    [line] = await audit_events(services, "activity.window")
    assert line["title"] == "127.0.0.1:8700/notice#d=4&t=<redacted>"
