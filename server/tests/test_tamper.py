from datetime import timedelta

from app.activity.tamper import TamperMonitor
from app.clock import to_kst_iso
from tests.mcp_helpers import login_as, make_user
from tests.test_auth_api import audit_events


async def test_report_logs_rings_and_publishes_to_authed_only(services, clock):
    anon = services.bus.subscribe(authed=False); authed = services.bus.subscribe(authed=True)
    rec = services.tamper.report("agent_exited", session_id=2, user="CORP\\hong", exit_code=1)
    assert rec == {"at": to_kst_iso(clock.now()), "event": "agent_exited", "session_id": 2, "user": "CORP\\hong", "exit_code": 1}
    assert list(anon.events) == [] and list(authed.events) == [("tamper", rec)]
    [line] = await audit_events(services, "tamper")
    assert (line["event"], line["exit_code"], line["ts"]) == ("agent_exited", 1, rec["at"])


async def test_recent_is_newest_first_and_bounded(services, clock):
    t = TamperMonitor(services.log, services.bus, clock, keep=3)
    for i in range(5):
        t.report("log_file_truncated", n=i)
    assert [r["n"] for r in t.recent(10)] == [4, 3, 2] and [r["n"] for r in t.recent(1)] == [4]


async def test_event_time_override(services, clock):
    at = clock.now() - timedelta(hours=1)
    assert services.tamper.report("log_cleared", at=at, channel="Security")["at"] == to_kst_iso(at)


async def test_tamper_api_requires_login_and_validates(external_client, services):
    assert (await external_client.get("/api/tamper/recent")).status_code == 401
    login_as(external_client, services, make_user(services, "d@x.com"), "external")
    services.tamper.report("log_cleared", channel="System")
    assert [r["event"] for r in (await external_client.get("/api/tamper/recent")).json()] == ["log_cleared"]
    assert (await external_client.get("/api/tamper/recent", params={"limit": 0})).status_code == 422
    assert (await external_client.get("/api/tamper/recent", params={"limit": 201})).json() == {"error": "validation"}
