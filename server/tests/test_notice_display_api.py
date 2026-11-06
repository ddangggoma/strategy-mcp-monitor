from app.notice.defaults import DEFAULT_NOTICE
from app.win.peer import PeerInfo
from tests.mcp_helpers import login_as, make_user
from tests.session_helpers import snap, ws
from tests.winfakes import FakePeerResolver

# F01: the RDP tracker is ``services.rdp`` (``services.sessions`` stays the login SessionStore).

EDGE2 = PeerInfo(100, 2, "CORP\\hong", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

def ticket(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    return services.displays.issue(services.displays.pending_for_session(2).id)

async def test_display_api_flow(local_client, services, clock):
    services.peers = FakePeerResolver(EDGE2); tk = ticket(services, clock)
    r = await local_client.post("/api/notice/display/open", headers={"X-Notice-Token": tk.token, "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200 and r.json() == {"display_id": tk.display_id, "version": 0, "title": DEFAULT_NOTICE.title,
                                                 "body": DEFAULT_NOTICE.body, "button_text": DEFAULT_NOTICE.button_text}
    assert (await local_client.post("/api/notice/display/ack", headers={"X-Notice-Token": tk.token})).status_code == 204
    assert services.displays.get(tk.display_id).closed_reason == "acknowledged"

async def test_display_api_rejects_missing_or_bad_token(local_client, services, clock):
    services.peers = FakePeerResolver(EDGE2); ticket(services, clock)
    for headers in ({}, {"X-Notice-Token": "bad"}):
        r = await local_client.post("/api/notice/display/open", headers=headers)
        assert (r.status_code, r.json()) == (404, {"error": "not_found"})

async def test_display_api_other_session_404(local_client, services, clock):
    services.peers = FakePeerResolver(PeerInfo(100, 3, "CORP\\kim", "msedge.exe")); tk = ticket(services, clock)
    assert (await local_client.post("/api/notice/display/ack", headers={"X-Notice-Token": tk.token})).status_code == 404
    assert services.displays.get(tk.display_id).closed_reason is None

async def test_cross_site_fetch_is_refused(local_client, services, clock):
    services.peers = FakePeerResolver(EDGE2); tk = ticket(services, clock)
    r = await local_client.post("/api/notice/display/open", headers={"X-Notice-Token": tk.token, "Sec-Fetch-Site": "cross-site"})
    assert (r.status_code, r.json()) == (403, {"error": "forbidden"})

async def test_display_routes_absent_on_external(external_client):
    for path in ("/api/notice/display/open", "/api/notice/display/ack"):
        assert (await external_client.post(path, headers={"X-Notice-Token": "x"})).status_code == 404

async def test_history_includes_notice(external_client, local_client, services, clock):
    services.peers = FakePeerResolver(EDGE2); tk = ticket(services, clock)
    await local_client.post("/api/notice/display/open", headers={"X-Notice-Token": tk.token})
    clock.advance(2); await local_client.post("/api/notice/display/ack", headers={"X-Notice-Token": tk.token})
    login_as(external_client, services, make_user(services, "d@x.com"), "external")
    [c] = (await external_client.get("/api/sessions/history")).json()["connections"]
    assert c["notice"] == {"version": 0, "attempts": 1, "first_shown_at": "2026-11-04T14:00:00.000+09:00",
                           "acknowledged_at": "2026-11-04T14:00:02.000+09:00", "ack_ms": 2000, "closed_reason": "acknowledged"}


# --- beyond the plan's tests -------------------------------------------------------------------

async def test_sec_fetch_site_none_and_same_site_rules(local_client, services, clock):
    services.peers = FakePeerResolver(EDGE2); tk = ticket(services, clock)
    r = await local_client.post("/api/notice/display/open", headers={"X-Notice-Token": tk.token, "Sec-Fetch-Site": "none"})
    assert r.status_code == 200
    for site in ("same-site", "cross-site"):
        r = await local_client.post("/api/notice/display/ack", headers={"X-Notice-Token": tk.token, "Sec-Fetch-Site": site})
        assert (r.status_code, r.json()) == (403, {"error": "forbidden"})
    assert services.displays.get(tk.display_id).closed_reason is None

async def test_unresolved_peer_is_not_found_and_reported(local_client, services, clock):
    services.peers = FakePeerResolver(None); tk = ticket(services, clock)
    r = await local_client.post("/api/notice/display/open", headers={"X-Notice-Token": tk.token})
    assert (r.status_code, r.json()) == (404, {"error": "not_found"})
    [rec] = services.tamper.recent(10)
    assert (rec["event"], rec["display_id"], rec["session_id"], rec["peer_session"]) == \
        ("notice_token_misuse", tk.display_id, 2, None)

async def test_ack_is_idempotent_and_open_after_ack_is_not_found(local_client, services, clock):
    services.peers = FakePeerResolver(EDGE2); tk = ticket(services, clock)
    h = {"X-Notice-Token": tk.token}
    assert (await local_client.post("/api/notice/display/ack", headers=h)).status_code == 204
    assert (await local_client.post("/api/notice/display/ack", headers=h)).status_code == 204
    assert (await local_client.post("/api/notice/display/open", headers=h)).status_code == 404

async def test_display_api_needs_no_login_or_csrf_and_resolves_the_tcp_peer(local_client, services, clock):
    peers = FakePeerResolver(EDGE2); services.peers = peers; tk = ticket(services, clock)
    login_as(local_client, services, make_user(services, "a@x.com", role="admin"), "local")  # a live session cookie
    r = await local_client.post("/api/notice/display/open", headers={"X-Notice-Token": tk.token})
    assert r.status_code == 200  # no X-CSRF-Token needed: the token header is the credential
    assert peers.calls == [("127.0.0.1", 123, 8700)]

async def test_history_notice_is_none_without_a_display(external_client, services, clock):
    [o] = services.rdp.apply(snap(clock.now(), ws(2)))
    services.db.execute("DELETE FROM notice_displays WHERE connection_id = ?", (o.connection.id,))
    login_as(external_client, services, make_user(services, "d@x.com"), "external")
    [c] = (await external_client.get("/api/sessions/history")).json()["connections"]
    assert c["notice"] is None
