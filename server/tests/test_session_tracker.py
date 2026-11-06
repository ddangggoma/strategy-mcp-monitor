from datetime import timedelta

from app.clock import to_kst_iso
from app.sessions.history import LogonFailureIn
from app.sessions.tracker import RDP_KEYS, Closed, LockChanged, Opened, SessionTracker
from tests.session_helpers import T0, snap, ws
from tests.test_auth_api import audit_events

# F01: the RDP tracker is ``services.rdp`` and its history ``services.rdp_history``
# (``services.sessions`` stays the login SessionStore).


def kinds(changes):
    return [(type(c).__name__, getattr(c, "reason", None)) for c in changes]

async def test_first_snapshot_opens_existing_for_active_rdp_only(services, clock):
    ch = services.rdp.apply(snap(clock.now(), ws(2), ws(3, state="disconnected"),
                                 ws(1, protocol="console", user="dev"), ws(4, user="")))
    assert [(type(c).__name__, c.connection.kind, c.session.session_id) for c in ch] == [("Opened", "existing", 2)]
    rows = services.rdp_history.connections(T0 - timedelta(days=1))
    assert [(r.session_id, r.kind, r.ended_at) for r in rows] == [(2, "existing", None)]

async def test_logon_disconnect_reconnect_logoff(services, clock):
    t = services.rdp; t.apply(snap(clock.now()))
    clock.advance(5); [o] = t.apply(snap(clock.now(), ws(2, logon=clock.now(), connected=clock.now())))
    assert isinstance(o, Opened) and o.connection.kind == "logon"
    logon, conn = o.connection.logon_at, o.connection.connected_at
    clock.advance(5); [c] = t.apply(snap(clock.now(), ws(2, state="disconnected", logon=logon, connected=conn)))
    assert (c.reason, c.connection_id) == ("disconnect", o.connection.id)
    clock.advance(5); [o2] = t.apply(snap(clock.now(), ws(2, logon=logon, connected=clock.now())))
    assert o2.connection.kind == "reconnect" and o2.connection.id != o.connection.id
    clock.advance(5); [c2] = t.apply(snap(clock.now()))
    assert (c2.reason, c2.connection_id) == ("logoff", o2.connection.id)
    assert [e["event"] for e in await audit_events(services, "session")] == ["connect", "disconnect", "connect", "logoff"]

async def test_fast_reconnect_detected_by_connect_time(services, clock):
    t = services.rdp; t.apply(snap(clock.now()))
    t.apply(snap(clock.now(), ws(2, logon=T0, connected=T0)))
    clock.advance(3)
    ch = t.apply(snap(clock.now(), ws(2, logon=T0, connected=T0 + timedelta(minutes=5))))
    assert kinds(ch) == [("Closed", "reconnected"), ("Opened", None)] and ch[1].connection.kind == "reconnect"

async def test_session_id_reuse_is_a_new_logon(services, clock):
    t = services.rdp; t.apply(snap(clock.now())); t.apply(snap(clock.now(), ws(2, logon=T0)))
    later = T0 + timedelta(hours=1)
    ch = t.apply(snap(clock.now(), ws(2, logon=later, connected=later)))
    assert kinds(ch) == [("Closed", "logoff"), ("Opened", None)] and ch[1].connection.kind == "logon"

async def test_console_needs_collect_console(services, clock):
    assert services.rdp.apply(snap(clock.now(), ws(1, protocol="console"))) == []
    t = SessionTracker(services.rdp_history, clock, services.log, services.bus, collect_console=True)
    [o] = t.apply(snap(clock.now(), ws(1, protocol="console")))
    assert o.connection.kind == "existing" and t.board_sessions()[0]["protocol"] == "console"

async def test_lock_events(services, clock):
    t = services.rdp; t.apply(snap(clock.now(), ws(2)))
    assert t.apply(snap(clock.now(), ws(2, locked=True))) == [LockChanged(2, True, clock.now())]
    assert t.board_sessions()[0]["state"] == "locked"
    assert [e["event"] for e in await audit_events(services, "session")] == ["connect", "lock"]

async def test_board_sessions_shape(services, clock):
    t = services.rdp
    assert t.board_sessions() is None and not t.ready
    t.apply(snap(clock.now(), ws(2, last_input=clock.now() - timedelta(seconds=125))))
    [s] = t.board_sessions()
    assert set(s) == RDP_KEYS and isinstance(s["connection_id"], int)
    assert {k: v for k, v in s.items() if k != "connection_id"} == {
        "session_id": 2, "user": "hong", "domain": "CORP", "client_name": "HONG-LAPTOP", "client_ip": "10.0.3.21",
        "reverse_dns": None, "logon_at": to_kst_iso(T0), "connected_at": to_kst_iso(T0), "state": "active",
        "idle_sec": 125, "resolution": "1920x1080@32", "notice_acknowledged": False, "client_build": 26100,
        "protocol": "rdp", "first_seen_ip": True, "first_seen_device": True}

async def test_publishes_sessions_only_on_visible_change(services, clock):
    sub = services.bus.subscribe(); t = services.rdp; li = clock.now()
    t.apply(snap(clock.now(), ws(2, last_input=li)))
    assert [n for n, _ in sub.events] == ["sessions"]; sub.events.clear()
    clock.advance(30); t.apply(snap(clock.now(), ws(2, last_input=li)))
    assert list(sub.events) == []
    clock.advance(31); t.apply(snap(clock.now(), ws(2, last_input=li)))
    assert [d["sessions"][0]["idle_sec"] for _, d in sub.events] == [61]

async def test_first_seen_flags(services, clock):
    t = services.rdp; t.apply(snap(clock.now()))
    [o1] = t.apply(snap(clock.now(), ws(2)))
    clock.advance(1); t.apply(snap(clock.now()))
    clock.advance(1); [o2] = t.apply(snap(clock.now(), ws(3, logon=clock.now(), name="hong-laptop")))
    clock.advance(1); t.apply(snap(clock.now()))
    clock.advance(1); [o3] = t.apply(snap(clock.now(), ws(4, logon=clock.now(), ip="10.0.9.9", name="OTHER")))
    assert [(o.connection.first_seen_ip, o.connection.first_seen_device) for o in (o1, o2, o3)] == \
        [(True, True), (False, False), (True, True)]

async def test_start_closes_dangling_rows(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    t2 = SessionTracker(services.rdp_history, clock, services.log, services.bus)
    clock.advance(60)
    assert t2.start() == 1
    [row] = services.rdp_history.connections(T0 - timedelta(days=1))
    assert (row.end_reason, row.ended_at) == ("service_stop", clock.now())

async def test_wts_failure_logged_once_per_minute_and_state_kept(services, clock):
    t = services.rdp; t.apply(snap(clock.now(), ws(2)))
    t.failed("boom"); clock.advance(30); t.failed("boom"); clock.advance(31); t.failed("boom")
    failures = [e for e in await audit_events(services, "system") if e.get("event") == "sessions.wts_failed"]
    assert len(failures) == 2 and failures[0]["error"] == "boom"
    assert len(t.board_sessions()) == 1

async def test_context_by_user_and_listener_order(services, clock):
    seen = []; t = services.rdp; t.add_listener(seen.append)
    t.apply(snap(clock.now(), ws(2), ws(3, user="kim", ip="10.0.0.9", name="KIM-PC")))
    ctx = t.context(3)
    assert (ctx.user, ctx.domain, ctx.client_ip, ctx.client_name, ctx.account) == ("kim", "CORP", "10.0.0.9", "KIM-PC", "CORP\\kim")
    assert t.by_user("KIM", "corp").session_id == 3 and t.by_user("kim", None).session_id == 3 and t.by_user("nobody", None) is None
    assert [c.session.session_id for c in seen] == [2, 3] and t.context(99) is None


# --- beyond the plan's list ------------------------------------------------------------------

async def test_session_log_lines_carry_connection_fields_and_snapshot_time(services, clock):
    t = services.rdp; t.apply(snap(clock.now()))
    clock.advance(5); [o] = t.apply(snap(clock.now(), ws(2, logon=clock.now(), connected=clock.now())))
    at_connect = clock.now()
    clock.advance(5); t.apply(snap(clock.now(), ws(2, state="disconnected", logon=at_connect, connected=at_connect,
                                                ip=None, name=None)))
    connect, disconnect = await audit_events(services, "session")
    common = {"connection_id": o.connection.id, "session_id": 2, "user": "CORP\\hong", "domain": "CORP",
              "client_ip": "10.0.3.21", "client_name": "HONG-LAPTOP", "client_build": 26100, "protocol": "rdp",
              "resolution": "1920x1080@32", "source": "wts"}
    assert connect == {"ts": to_kst_iso(at_connect), "cat": "session", "event": "connect", "kind": "logon", **common}
    # the disconnect line keeps the connection's client fields even though WTS no longer reports them
    assert disconnect == {"ts": to_kst_iso(clock.now()), "cat": "session", "event": "disconnect", **common}
    [row] = services.rdp_history.connections(T0 - timedelta(days=1))
    assert (row.end_reason, row.ended_at) == ("disconnect", clock.now())

async def test_fast_reconnect_logs_the_missed_disconnect(services, clock):
    t = services.rdp; [o] = t.apply(snap(clock.now(), ws(2)))
    clock.advance(3); c, o2 = t.apply(snap(clock.now(), ws(2, connected=clock.now())))
    assert c == Closed(o.connection.id, 2, "reconnected", clock.now())
    lines = [(e["event"], e.get("kind"), e.get("reason"), e["connection_id"]) for e in await audit_events(services, "session")]
    assert lines == [("connect", "existing", None, o.connection.id), ("disconnect", None, "reconnected", o.connection.id),
                     ("connect", "reconnect", None, o2.connection.id)]
    assert services.rdp_history.get(o.connection.id).end_reason == "reconnected"

async def test_logoff_of_a_disconnected_session_logs_without_a_change(services, clock):
    t = services.rdp; t.apply(snap(clock.now(), ws(2, state="disconnected")))
    assert t.apply(snap(clock.now())) == []
    [line] = await audit_events(services, "session")
    assert (line["event"], line["connection_id"], line["session_id"], line["user"]) == ("logoff", None, 2, "CORP\\hong")

async def test_first_snapshot_disconnected_then_active_is_reconnect(services, clock):
    t = services.rdp; t.apply(snap(clock.now(), ws(2, state="disconnected")))
    clock.advance(5); [o] = t.apply(snap(clock.now(), ws(2, connected=clock.now())))
    assert o.connection.kind == "reconnect"

async def test_logon_seen_connected_before_active_is_still_a_logon(services, clock):
    t = services.rdp; t.apply(snap(clock.now()))
    clock.advance(1); assert t.apply(snap(clock.now(), ws(2, state="connected", logon=clock.now()))) == []
    logon = clock.now(); clock.advance(1)
    [o] = t.apply(snap(clock.now(), ws(2, logon=logon, connected=clock.now())))
    assert o.connection.kind == "logon"

async def test_lock_only_tracked_while_connected(services, clock):
    t = services.rdp; t.apply(snap(clock.now(), ws(2)))
    clock.advance(1)
    assert kinds(t.apply(snap(clock.now(), ws(2, state="disconnected", locked=True)))) == [("Closed", "disconnect")]
    clock.advance(1)
    assert kinds(t.apply(snap(clock.now(), ws(2, connected=clock.now(), locked=True)))) == [("Opened", None)]
    clock.advance(1)
    assert t.apply(snap(clock.now(), ws(2, connected=clock.now() - timedelta(seconds=1), locked=False))) == \
        [LockChanged(2, False, clock.now())]

async def test_board_excludes_disconnected_and_current_lists_all(services, clock):
    t = services.rdp; li = clock.now() - timedelta(seconds=10)
    t.apply(snap(clock.now(), ws(2, locked=True, last_input=li), ws(3, user="kim", state="disconnected")))
    assert [(s["session_id"], s["state"]) for s in t.board_sessions()] == [(2, "locked")]
    cur = t.current()
    assert [(c["session_id"], c["state"], c["connection_id"] is None) for c in cur] == \
        [(2, "locked", False), (3, "disconnected", True)]
    assert cur[0] == {"session_id": 2, "user": "hong", "domain": "CORP", "state": "locked",
                      "client_name": "HONG-LAPTOP", "client_ip": "10.0.3.21", "protocol": "rdp",
                      "logon_at": to_kst_iso(T0), "connected_at": to_kst_iso(T0), "disconnected_at": None,
                      "idle_sec": 10, "connection_id": t.connection_of(2)}
    assert t.connection_of(3) is None and t.context(3).connection_id is None

async def test_notice_state_and_reverse_dns_update_board_and_publish(services, clock):
    sub = services.bus.subscribe(); t = services.rdp
    t.set_notice_state(1, True)  # before ready: nothing published, unknown connection ignored
    assert list(sub.events) == []
    [o] = t.apply(snap(clock.now(), ws(2))); sub.events.clear()
    cid = o.connection.id
    t.set_notice_state(cid, True)  # opening already set False through the display listener (Task 11)
    t.set_reverse_dns(cid, "hong-laptop.corp")
    t.set_reverse_dns(cid, "hong-laptop.corp")  # no visible change, no event
    assert [(d["sessions"][0]["notice_acknowledged"], d["sessions"][0]["reverse_dns"]) for _, d in sub.events] == \
        [(True, None), (True, "hong-laptop.corp")]
    assert services.rdp_history.get(cid).reverse_dns == "hong-laptop.corp"
    # a closed connection still gets its history row updated (DNS can arrive late)
    clock.advance(1); t.apply(snap(clock.now()))
    t.set_reverse_dns(cid, "late.corp")
    assert services.rdp_history.get(cid).reverse_dns == "late.corp"

async def test_listener_failure_is_logged_and_others_still_run(services, clock):
    seen = []; t = services.rdp
    def boom(change):
        raise RuntimeError("listener broke")
    t.add_listener(boom); t.add_listener(seen.append)
    t.apply(snap(clock.now(), ws(2)))
    assert len(seen) == 1 and t.ready
    [fail] = [e for e in await audit_events(services, "system") if e.get("event") == "sessions.listener_failed"]
    assert fail["error"] == "RuntimeError('listener broke')"

async def test_listeners_see_ready_state_on_the_first_snapshot(services, clock):
    sub = services.bus.subscribe(); t = services.rdp
    def ack(change):
        assert t.ready and t.connection_of(change.session.session_id) == change.connection.id
        t.set_notice_state(change.connection.id, False)
    t.add_listener(ack)
    t.apply(snap(clock.now(), ws(2)))
    assert [d["sessions"][0]["notice_acknowledged"] for _, d in sub.events] == [False]

async def test_history_failures_and_pagination(services, clock):
    h = services.rdp_history
    f = LogonFailureIn(at=clock.now(), user="hong", domain="CORP", client_ip="10.0.3.21", workstation="HONG-LAPTOP",
                       logon_type=10, status="0xc000006d", sub_status="0xc000006a", source="eventlog:4625",
                       record_id=7)
    first = h.add_failure(f)
    assert isinstance(first, int) and h.add_failure(f) is None
    later = h.add_failure(LogonFailureIn(clock.now() + timedelta(seconds=1), None, None, None, None, None, None,
                                         None, "eventlog:4625", 8))
    assert [x.id for x in h.failures(clock.now() - timedelta(hours=1))] == [later, first]
    assert h.failures(clock.now() - timedelta(hours=1))[1].sub_status == "0xc000006a"
    assert h.failures(clock.now() + timedelta(seconds=2)) == []
    ids = [h.open(ws(2, logon=clock.now()), "logon", clock.now()).id for _ in range(3)]
    assert [c.id for c in h.connections(T0, limit=2)] == ids[:0:-1]
    assert [c.id for c in h.connections(T0, before_id=ids[1])] == [ids[0]]
    h.close(ids[0], clock.now(), "logoff"); h.close(ids[0], clock.now() + timedelta(1), "disconnect")
    assert (h.get(ids[0]).end_reason, h.get(ids[0]).ended_at) == ("logoff", clock.now())
    assert h.get(999) is None
