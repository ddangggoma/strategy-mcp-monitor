import asyncio
import csv
import io
import json
import threading
from datetime import UTC, datetime

import pytest

from app.clock import to_kst_iso
from app.logstore.indexer import LogIndex
from app.logstore.query import LogRow
from app.web import logs_api
from app.web.logs_api import ViewAuditThrottle
from tests.fakes import FakeClock
from tests.log_helpers import ev, index_all, write_lines
from tests.mcp_helpers import login_as, make_user
from tests.test_auth_api import audit_events

FROM, TO = "2026-11-04T13:00:00.000+09:00", "2026-11-04T14:00:00.000+09:00"
P = {"from": FROM, "to": TO}
AUTH_LINE = dict(event="login", email="a@x.com", channel="local", ip="127.0.0.1", ok=False)


async def seed(services):
    write_lines(services.paths.logs_dir, "2026-11-04", [
        ev(f"2026-11-04T13:{i:02d}:00.000+09:00", "activity.command", user="CORP\\hong", session_id=2,
           client_ip="10.0.3.21", client_name="HONG-LAPTOP", text=f"=cmd {i}") for i in range(5)])
    write_lines(services.paths.logs_dir, "2026-11-04", [
        ev("2026-11-04T13:30:00.000+09:00", "admin.audit", action="user_create", actor_email="a@x.com",
           channel="local", ip="127.0.0.1", target={"email": "b@x.com"}, result="ok"),
        ev("2026-11-04T13:31:00.000+09:00", "admin.audit", action="settings_update", actor_email="d@x.com",
           channel="external", ip="10.0.0.9", target={"path": "/api/settings"}, result="denied"),
        ev("2026-11-04T13:32:00.000+09:00", "auth", **AUTH_LINE)])
    await index_all(services)


def dev(client, services, channel="external"):
    return login_as(client, services, make_user(services, f"d-{channel}@x.com"), channel)


async def test_logs_require_login(external_client):
    r = await external_client.get("/api/logs", params=P)
    assert (r.status_code, r.json()) == (401, {"error": "login_required"})


async def test_list_items_shape_and_cursor(external_client, services):
    dev(external_client, services); await seed(services)
    q = {**P, "limit": 2, "users": ["corp\\hong"], "cat": ["activity.command"]}
    body = (await external_client.get("/api/logs", params=q)).json()
    item = body["items"][0]
    assert set(item) == {"id", "ts", "cat", "event", "user", "session_id", "client_ip", "outcome", "data"}
    assert (item["ts"], item["data"]["text"], item["session_id"]) == ("2026-11-04T13:04:00.000+09:00", "=cmd 4", 2)
    assert body["index"] == {"ready": True}
    r2 = (await external_client.get("/api/logs", params={**q, "cursor": body["next_cursor"]})).json()
    assert [i["data"]["text"] for i in r2["items"]] == ["=cmd 2", "=cmd 1"]


@pytest.mark.parametrize("params", [
    {"from": "2026-11-04T13:00:00", "to": TO}, {"from": TO, "to": FROM}, {**P, "cat": "nope"},
    {**P, "users": [f"u{i}" for i in range(51)]}, {**P, "cursor": "!!"}, {**P, "limit": 1001},
    {**P, "q": "x" * 501}, {**P, "outcome": "maybe"}, {"from": "yesterday", "to": TO}])
async def test_validation_422(external_client, services, params):
    dev(external_client, services)
    r = await external_client.get("/api/logs", params=params)
    assert (r.status_code, r.json()) == (422, {"error": "validation"})


async def test_defaults_to_the_last_hour(external_client, services):
    dev(external_client, services)
    assert (await external_client.get("/api/logs")).status_code == 200


async def test_histogram_users_and_status(external_client, services):
    dev(external_client, services); await seed(services)
    h = (await external_client.get("/api/logs/histogram", params={**P, "buckets": 10, "group": "cat"})).json()
    assert h["bucket_sec"] == 600 and h["starts"][0] == FROM and h["source"] == "rollup"
    assert {s["key"]: sum(s["counts"]) for s in h["series"]} == {"activity.command": 5, "auth": 1, "admin.audit": 2}
    users = (await external_client.get("/api/logs/users", params=P)).json()
    assert users[0] == {"user": "CORP\\hong", "count": 5}
    st = (await external_client.get("/api/logs/status")).json()
    assert st["ready"] is True and st["rows"] == 8 and st["newest_day"] == "2026-11-04"


async def test_export_csv_escapes_formulas_and_has_bom(external_client, services):
    dev(external_client, services); await seed(services)
    r = await external_client.get("/api/logs/export", params={**P, "format": "csv", "cat": ["activity.command"]})
    assert r.headers["content-type"] == "text/csv; charset=utf-8" and r.headers["cache-control"] == "no-store"
    assert r.headers["content-disposition"] == 'attachment; filename="mcp-logs-20261104-1300-20261104-1400.csv"'
    text = r.content.decode("utf-8")
    assert text.startswith("﻿ts,cat,event,user,session_id,client_ip,client_name,outcome,summary\r\n")
    assert "2026-11-04T13:04:00.000+09:00,activity.command,,CORP\\hong,2,10.0.3.21,HONG-LAPTOP,,'=cmd 4\r\n" in text


async def test_export_jsonl_is_the_raw_lines(external_client, services):
    dev(external_client, services); await seed(services)
    r = await external_client.get("/api/logs/export", params={**P, "format": "jsonl", "cat": ["auth"]})
    assert r.headers["content-type"] == "application/x-ndjson; charset=utf-8"
    assert r.text == ev("2026-11-04T13:32:00.000+09:00", "auth", **AUTH_LINE).decode() + "\n"


async def test_first_page_views_are_audited_with_throttle(external_client, services):
    dev(external_client, services); await seed(services)
    await external_client.get("/api/logs", params=P)                      # recorded
    await external_client.get("/api/logs", params=P)                      # same filters within 60 s: skipped
    services.clock.advance(61)
    await external_client.get("/api/logs", params=P)                      # recorded
    await external_client.get("/api/logs", params={**P, "q": "cmd"})      # other filters: recorded
    body = (await external_client.get("/api/logs", params={**P, "limit": 1})).json()   # limit is not a filter: skipped
    await external_client.get("/api/logs", params={**P, "limit": 1, "cursor": body["next_cursor"]})  # cursor: never
    await external_client.get("/api/logs/export", params={**P, "format": "jsonl"})
    events = await audit_events(services, "admin.audit")
    views = [e for e in events if e["action"] == "logs_view"]
    assert len(views) == 3 and views[2]["target"]["filters"]["q"] == "cmd"
    exports = [e for e in events if e["action"] == "logs_export"]
    assert len(exports) == 1 and exports[0]["target"]["format"] == "jsonl"


async def test_audit_endpoint_restricts_categories_and_filters(external_client, services):
    dev(external_client, services); await seed(services)
    admin = (await external_client.get("/api/audit", params=P)).json()["items"]
    assert {i["cat"] for i in admin} == {"admin.audit"} and len(admin) == 2
    denied = (await external_client.get("/api/audit", params={**P, "result": ["denied"]})).json()["items"]
    assert [i["event"] for i in denied] == ["settings_update"]
    local = (await external_client.get("/api/audit", params={**P, "kind": "all", "channel": "local"})).json()["items"]
    assert {i["cat"] for i in local} == {"admin.audit", "auth"} and len(local) == 2


async def test_logs_work_on_both_channels(local_client, external_client, services):
    await seed(services)
    for client, channel in ((local_client, "local"), (external_client, "external")):
        dev(client, services, channel)
        assert (await client.get("/api/logs", params=P)).status_code == 200


# -- beyond the plan's tests ------------------------------------------------------------------------

async def views_of(services, action):
    await services.log.flush()
    if not (services.paths.logs_dir / "2026-11-04.jsonl").exists():  # nothing was logged at all
        return []
    return [e for e in await audit_events(services, "admin.audit") if e["action"] == action]


@pytest.mark.parametrize("path", [
    "/api/logs/histogram", "/api/logs/users", "/api/logs/status", "/api/audit",
    "/api/logs/export?format=csv", "/api/audit/export?format=jsonl"])
async def test_every_route_requires_login(external_client, path):
    r = await external_client.get(path)
    assert (r.status_code, r.json()) == (401, {"error": "login_required"})


async def test_login_is_checked_before_the_parameters(external_client):
    r = await external_client.get("/api/logs", params={"from": "yesterday", "limit": 0})
    assert (r.status_code, r.json()) == (401, {"error": "login_required"})


async def test_defaults_are_the_hour_before_now_and_recorded_as_filters(external_client, services):
    dev(external_client, services); await index_all(services)
    assert (await external_client.get("/api/logs")).json() == {"items": [], "next_cursor": None,
                                                              "index": {"ready": True}}
    (view,) = await views_of(services, "logs_view")
    assert view["target"] == {"filters": {"from": "2026-11-04T13:00:00.000+09:00",
                                          "to": "2026-11-04T14:00:00.000+09:00"}}
    assert (view["channel"], view["actor_email"], view["result"]) == ("external", "d-external@x.com", "ok")


@pytest.mark.parametrize("params", [
    {"from": "2026-11-04T13:00:00Z", "to": "2026-11-04T05:00:00Z"}, {"from": "2026-11-04T14:00:00+09:00"},
    {"from": "2026-11-04", "to": TO}, {**P, "session": -1}, {**P, "session": 2**31}, {**P, "ip": ""},
    {**P, "ip": "x" * 65}, {**P, "event": [f"e{i}" for i in range(21)]}, {**P, "limit": 0},
    {"from": "0001-01-01T00:00:00+09:00", "to": TO}, {**P, "q": " ".join(["w"] * 11)}])
async def test_more_validation_422(external_client, services, params):
    dev(external_client, services)
    r = await external_client.get("/api/logs", params=params)
    assert (r.status_code, r.json()) == (422, {"error": "validation"})


@pytest.mark.parametrize("params", [{"from": FROM}, {"to": TO}, {"from": "2026-11-04T04:00:00Z"}])
async def test_one_bound_alone_uses_the_default_of_the_other(external_client, services, params):
    """``to`` defaults to now (14:00 KST) and ``from`` to an hour before ``to``."""
    dev(external_client, services)
    assert (await external_client.get("/api/logs", params=params)).status_code == 200
    (view,) = await views_of(services, "logs_view")
    assert view["target"]["filters"] == {"from": FROM, "to": TO}


async def test_the_full_filter_is_recorded_without_empty_values(external_client, services):
    dev(external_client, services); await seed(services)
    q = {"from": "2026-11-04T04:00:00Z", "to": TO, "users": ["CORP\\hong"], "cat": ["activity.command"],
         "event": ["x"], "outcome": ["ok"], "session": 2, "ip": "10.0.3.21", "q": "cmd", "limit": 5}
    assert (await external_client.get("/api/logs", params=q)).status_code == 200
    (view,) = await views_of(services, "logs_view")
    assert view["target"]["filters"] == {
        "from": FROM, "to": TO, "users": ["CORP\\hong"], "cat": ["activity.command"], "event": ["x"],
        "outcome": ["ok"], "session": 2, "ip": "10.0.3.21", "q": "cmd"}


async def test_filter_order_of_keys_does_not_defeat_the_throttle(external_client, services):
    dev(external_client, services)
    await external_client.get("/api/logs", params=[("from", FROM), ("to", TO), ("q", "a")])
    await external_client.get("/api/logs", params=[("q", "a"), ("to", TO), ("from", FROM)])
    assert len(await views_of(services, "logs_view")) == 1


async def test_failed_queries_are_not_recorded_as_views(external_client, services):
    dev(external_client, services)
    assert (await external_client.get("/api/logs", params={**P, "cursor": "!!"})).status_code == 422
    assert (await external_client.get("/api/logs", params={**P, "cat": "nope"})).status_code == 422
    assert await views_of(services, "logs_view") == []


async def test_histogram_users_and_status_are_never_recorded(external_client, services):
    dev(external_client, services); await seed(services)
    await external_client.get("/api/logs/histogram", params=P)
    await external_client.get("/api/logs/users", params=P)
    await external_client.get("/api/logs/status")
    actions = {e["action"] for e in await audit_events(services, "admin.audit")}
    assert actions == {"user_create", "settings_update"}


async def test_histogram_shape_and_scan_source(external_client, services):
    dev(external_client, services); await seed(services)
    h = (await external_client.get("/api/logs/histogram", params={**P, "q": "cmd", "buckets": 10})).json()
    assert set(h) == {"from", "to", "bucket_sec", "starts", "series", "total", "source"}
    assert (h["from"], h["to"], h["bucket_sec"], h["total"], h["source"]) == (FROM, TO, 600, 5, "scan")
    assert h["starts"][-1] == "2026-11-04T13:50:00.000+09:00" and len(h["starts"]) == 6
    assert h["series"] == [{"key": None, "counts": [5, 0, 0, 0, 0, 0]}]


@pytest.mark.parametrize("params", [{"buckets": 9}, {"buckets": 201}, {"group": "ip"}])
async def test_histogram_validation(external_client, services, params):
    dev(external_client, services)
    r = await external_client.get("/api/logs/histogram", params={**P, **params})
    assert (r.status_code, r.json()) == (422, {"error": "validation"})


async def test_users_facet_ignores_the_users_condition_and_limits(external_client, services):
    dev(external_client, services); await seed(services)
    users = (await external_client.get("/api/logs/users", params={**P, "users": ["nobody"]})).json()
    assert users == [{"user": "CORP\\hong", "count": 5}, {"user": "a@x.com", "count": 2},
                     {"user": "d@x.com", "count": 1}]
    one = (await external_client.get("/api/logs/users", params={**P, "limit": 1})).json()
    assert one == [{"user": "CORP\\hong", "count": 5}]
    assert (await external_client.get("/api/logs/users", params={**P, "limit": 501})).status_code == 422


async def test_status_fields(external_client, services):
    dev(external_client, services); await seed(services)
    st = (await external_client.get("/api/logs/status")).json()
    assert st == {"ready": True, "rebuilding": False, "files": 1, "pending_files": 0, "pending_bytes": 0,
                  "rows": 8, "bad_lines": 0, "oldest_day": "2026-11-04", "newest_day": "2026-11-04",
                  "last_indexed_at": "2026-11-04T14:00:00.000+09:00"}


async def test_audit_kinds_users_and_query(external_client, services):
    dev(external_client, services); await seed(services)
    auth = (await external_client.get("/api/audit", params={**P, "kind": "auth"})).json()
    assert [i["cat"] for i in auth["items"]] == ["auth"] and auth["index"] == {"ready": True}
    by_user = (await external_client.get("/api/audit", params={**P, "kind": "all", "users": ["A@X.COM"]})).json()
    assert [i["event"] for i in by_user["items"]] == ["login", "user_create"]
    found = (await external_client.get("/api/audit", params={**P, "q": "settings"})).json()
    assert [i["event"] for i in found["items"]] == ["settings_update"]
    paged = (await external_client.get("/api/audit", params={**P, "limit": 1})).json()
    rest = (await external_client.get("/api/audit", params={**P, "cursor": paged["next_cursor"]})).json()
    assert [i["event"] for i in paged["items"] + rest["items"]] == ["settings_update", "user_create"]


@pytest.mark.parametrize("params", [{"kind": "system"}, {"channel": "lan"}, {"result": "maybe"}])
async def test_audit_validation(external_client, services, params):
    dev(external_client, services)
    r = await external_client.get("/api/audit", params={**P, **params})
    assert (r.status_code, r.json()) == (422, {"error": "validation"})


async def test_audit_views_are_recorded_with_kind_and_channel(external_client, services):
    dev(external_client, services); await seed(services)
    q = {**P, "kind": "all", "channel": "local", "result": ["ok", "fail"]}
    await external_client.get("/api/audit", params=q)
    await external_client.get("/api/audit", params=q)  # throttled
    await external_client.get("/api/audit", params=P)  # other filters
    views = await views_of(services, "audit_view")
    assert [v["target"]["filters"] for v in views] == [
        {"from": FROM, "to": TO, "outcome": ["ok", "fail"], "kind": "all", "channel": "local"},
        {"from": FROM, "to": TO, "kind": "admin"}]
    assert await views_of(services, "logs_view") == []


async def test_audit_export_is_csv_of_audit_rows_and_recorded(external_client, services):
    dev(external_client, services); await seed(services)
    r = await external_client.get("/api/audit/export", params={**P, "format": "csv", "limit": 10})
    assert r.headers["content-disposition"] == 'attachment; filename="mcp-audit-20261104-1300-20261104-1400.csv"'
    assert r.headers["x-content-type-options"] == "nosniff"
    lines = r.content.decode("utf-8").split("\r\n")
    assert lines[1:] == [
        "2026-11-04T13:31:00.000+09:00,admin.audit,settings_update,d@x.com,,10.0.0.9,,denied,settings_update",
        "2026-11-04T13:30:00.000+09:00,admin.audit,user_create,a@x.com,,127.0.0.1,,ok,user_create", ""]
    (export,) = await views_of(services, "audit_export")
    assert export["target"] == {"filters": {"from": FROM, "to": TO, "kind": "admin"}, "format": "csv", "limit": 10}


async def test_every_export_is_recorded(external_client, services):
    dev(external_client, services)
    for _ in range(2):
        assert (await external_client.get("/api/logs/export", params={**P, "format": "csv"})).status_code == 200
    exports = await views_of(services, "logs_export")
    assert [e["target"] for e in exports] == [{"filters": P, "format": "csv", "limit": 100000}] * 2


@pytest.mark.parametrize("params", [{}, {"format": "xlsx"}, {"format": "csv", "limit": 100001},
                                    {"format": "csv", "limit": 0}])
async def test_export_validation(external_client, services, params):
    dev(external_client, services)
    r = await external_client.get("/api/logs/export", params={**P, **params})
    assert (r.status_code, r.json()) == (422, {"error": "validation"})
    assert await views_of(services, "logs_export") == []


async def test_export_streams_in_chunks_up_to_the_limit(external_client, services):
    dev(external_client, services)
    lines = [ev(f"2026-11-04T13:{i // 60:02d}:{i % 60:02d}.{i % 1000:03d}+09:00", "activity.process", n=i)
             for i in range(2500)]
    write_lines(services.paths.logs_dir, "2026-11-04", lines)
    await index_all(services)
    r = await external_client.get("/api/logs/export", params={**P, "format": "jsonl", "limit": 2100})
    got = [json.loads(line)["n"] for line in r.text.splitlines()]
    assert got == list(range(2499, 399, -1))
    full = await external_client.get("/api/logs/export", params={**P, "format": "csv"})
    assert full.content.decode("utf-8").count("\r\n") == 2501  # header + every row


async def test_csv_cells_summary_and_client_name(external_client, services):
    dev(external_client, services)
    write_lines(services.paths.logs_dir, "2026-11-04", [
        ev("2026-11-04T13:01:00.000+09:00", "activity.process", user="+evil", exe=7, name="calc.exe",
           client_name=42, cmdline="@x"),
        ev("2026-11-04T13:02:00.000+09:00", "activity.window", user="-u", title="a,\"b\"\nc" + "z" * 3000),
        ev("2026-11-04T13:03:00.000+09:00", "system", event="\tx", text=["not", "a", "string"]),
        ev("2026-11-04T13:04:00.000+09:00", "session", client_ip="\r1", event="logon_failed")])
    await index_all(services)
    r = await external_client.get("/api/logs/export", params={**P, "format": "csv", "cat": [
        "activity.process", "activity.window", "system", "session"]})
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"), newline="")))
    assert rows[1] == ["2026-11-04T13:04:00.000+09:00", "session", "logon_failed", "", "", "'\r1", "", "fail", ""]
    assert rows[2] == ["2026-11-04T13:03:00.000+09:00", "system", "'\tx", "", "", "", "", "", ""]
    assert rows[3][:4] == ["2026-11-04T13:02:00.000+09:00", "activity.window", "", "'-u"]
    assert rows[3][8] == ("a,\"b\"\nc" + "z" * 3000)[:2000]
    assert rows[4][3] == "'+evil" and rows[4][6] == "42" and rows[4][8] == "'@x"


async def test_queries_run_inside_the_query_slots(external_client, services, monkeypatch):
    """Every index call of the API goes through ``LogIndex.query`` (the four slots)."""
    dev(external_client, services); await seed(services)
    calls: list[str] = []
    real = LogIndex.query

    async def spy(self, fn, *args):
        calls.append(fn.__name__)
        return await real(self, fn, *args)

    monkeypatch.setattr(LogIndex, "query", spy)
    await external_client.get("/api/logs", params=P)
    await external_client.get("/api/logs/histogram", params=P)
    await external_client.get("/api/logs/users", params=P)
    await external_client.get("/api/audit", params=P)
    await external_client.get("/api/logs/export", params={**P, "format": "jsonl", "cat": ["auth"]})
    assert calls == ["page", "histogram", "users", "page", "take"]


async def test_query_slots_bound_concurrency_and_outlive_a_cancelled_caller(services):
    index = services.log_index
    assert index.query_slots._value == 4  # type: ignore[attr-defined]
    gate, running, peak, lock = threading.Event(), [0], [0], threading.Lock()

    def work(x):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        gate.wait(5)
        with lock:
            running[0] -= 1
        return x

    tasks = [asyncio.create_task(index.query(work, i)) for i in range(6)]
    for _ in range(100):
        await asyncio.sleep(0.01)
        if running[0] == 4:
            break
    assert running[0] == 4
    tasks[0].cancel()  # its thread keeps running: the slot stays taken until the thread ends
    await asyncio.sleep(0.05)
    assert running[0] == 4 and index.query_slots.locked()
    gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert isinstance(results[0], asyncio.CancelledError) and results[1:] == [1, 2, 3, 4, 5]
    assert peak[0] == 4 and not index.query_slots.locked()


def test_view_audit_throttle_window_and_eviction():
    clock = FakeClock(datetime(2026, 11, 4, tzinfo=UTC))
    t = ViewAuditThrottle(clock, window_sec=60, max_keys=3)
    assert t.allow(("a",)) and not t.allow(("a",))
    clock.advance(59.999)
    assert not t.allow(("a",))
    clock.advance(0.001)
    assert t.allow(("a",))
    assert t.allow(("b",)) and t.allow(("c",)) and t.allow(("d",))  # full: "a" (oldest) is dropped
    assert len(t) == 3 and t.allow(("a",)) and not t.allow(("d",))


def test_log_item_shape():
    row = LogRow(id=7, ts_ms=1_793_768_400_000, cat="auth", event="login", user="a@x.com", session_id=None,
                 client_ip="1.2.3.4", outcome="fail", data={"ok": False}, raw="{}")
    assert logs_api.log_item(row) == {
        "id": 7, "ts": to_kst_iso(datetime.fromtimestamp(1_793_768_400, UTC)),
        "cat": "auth", "event": "login", "user": "a@x.com", "session_id": None, "client_ip": "1.2.3.4",
        "outcome": "fail", "data": {"ok": False}}
