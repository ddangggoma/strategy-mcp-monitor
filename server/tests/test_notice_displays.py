import pytest

from app.notice.content import NoticeContent
from app.notice.displays import DisplayNotFoundError, NoticeDisplays
from tests.session_helpers import T0, snap, ws
from tests.test_auth_api import audit_events

# F01: the RDP tracker is ``services.rdp`` (``services.sessions`` stays the login SessionStore).


async def notice_events(services):
    return await audit_events(services, "notice")

async def test_create_pins_version_and_marks_board_unacknowledged(services, clock):
    services.notice.save(NoticeContent("안내", "본문", "확인"), None)  # version 1
    [o] = services.rdp.apply(snap(clock.now(), ws(2)))
    d = services.displays.pending_for_session(2)
    assert (d.version, d.kind, d.connection_id, d.attempts, d.closed_reason) == (1, "existing", o.connection.id, 0, None)
    assert services.rdp.board_sessions()[0]["notice_acknowledged"] is False
    services.notice.save(NoticeContent("안내", "바뀐 본문", "확인"), None)  # a later edit does not change this display
    tk = services.displays.issue(d.id)
    assert services.displays.open(tk.token, peer_session=2)[1].body == "본문"

async def test_open_and_ack_flow_logs_and_marks_board(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    tk = services.displays.issue(services.displays.pending_for_session(2).id)
    services.displays.open(tk.token, peer_session=2)
    services.displays.open(tk.token, peer_session=2)  # a reload of the same attempt logs nothing new
    clock.advance(4.25)
    d = services.displays.acknowledge(tk.token, peer_session=2)
    assert (d.closed_reason, d.ack_ms) == ("acknowledged", 4250)
    ev = await notice_events(services)
    assert [e["event"] for e in ev] == ["notice_shown", "notice_acknowledged"]
    assert (ev[0]["kind"], ev[0]["version"], ev[0]["attempt"], ev[1]["elapsed_ms"]) == ("existing", 0, 1, 4250)
    assert services.rdp.board_sessions()[0]["notice_acknowledged"] is True
    assert services.displays.acknowledge(tk.token, peer_session=2).closed_reason == "acknowledged"
    assert len(await notice_events(services)) == 2

async def test_reconnect_supersedes_pending_display(services, clock):
    t = services.rdp; t.apply(snap(clock.now()))
    t.apply(snap(clock.now(), ws(2, logon=T0, connected=T0)))
    first = services.displays.pending_for_session(2)
    clock.advance(10); t.apply(snap(clock.now(), ws(2, state="disconnected", logon=T0, connected=T0)))
    assert services.displays.pending_for_session(2).id == first.id
    clock.advance(10); t.apply(snap(clock.now(), ws(2, logon=T0, connected=clock.now())))
    second = services.displays.pending_for_session(2)
    assert second.id != first.id and second.kind == "reconnect"
    assert services.displays.get(first.id).closed_reason == "superseded"
    un = [e for e in await notice_events(services) if e["event"] == "notice_unacknowledged"]
    assert [(e["display_id"], e["reason"]) for e in un] == [(first.id, "superseded")]

async def test_wrong_token_or_other_session_is_not_found_and_reported(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    tk = services.displays.issue(services.displays.pending_for_session(2).id)
    with pytest.raises(DisplayNotFoundError):
        services.displays.open("nope", peer_session=2)
    with pytest.raises(DisplayNotFoundError):
        services.displays.open(tk.token, peer_session=3)
    with pytest.raises(DisplayNotFoundError):
        services.displays.acknowledge(tk.token, peer_session=None)
    misuse = [r for r in services.tamper.recent(10) if r["event"] == "notice_token_misuse"]
    assert [(r["session_id"], r["peer_session"]) for r in misuse] == [(2, 3)]  # None: unresolved (M2)

async def test_reissue_invalidates_old_token_and_counts_attempts(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    d = services.displays.pending_for_session(2)
    old = services.displays.issue(d.id); new = services.displays.issue(d.id)
    assert (old.attempt, new.attempt, services.displays.get(d.id).attempts) == (1, 2, 2)
    with pytest.raises(DisplayNotFoundError):
        services.displays.open(old.token, peer_session=2)
    services.displays.open(new.token, peer_session=2)
    assert (await notice_events(services))[0]["attempt"] == 2

async def test_logoff_and_unacknowledged_reasons(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    d = services.displays.pending_for_session(2)
    services.displays.unacknowledged(d.id, "window_closed")
    assert services.displays.pending_for_session(2).id == d.id
    services.rdp.apply(snap(clock.now()))  # logoff
    assert services.displays.get(d.id).closed_reason == "logoff" and services.displays.pending_for_session(2) is None
    assert [e["reason"] for e in await notice_events(services) if e["event"] == "notice_unacknowledged"] == ["window_closed", "logoff"]

async def test_start_closes_pending_as_service_restart(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    d = services.displays.pending_for_session(2)
    again = NoticeDisplays(services.db, clock, services.log, services.notice, services.rdp, services.tamper)
    assert again.start() == 1 and services.displays.get(d.id).closed_reason == "service_restart"


# --- beyond the plan's tests -------------------------------------------------------------------

async def test_event_fields_carry_the_session_context(services, clock):
    [o] = services.rdp.apply(snap(clock.now(), ws(2)))
    d = services.displays.pending_for_session(2)
    tk = services.displays.issue(d.id)
    services.displays.open(tk.token, peer_session=2)
    clock.advance(1); services.displays.acknowledge(tk.token, peer_session=2)
    shown, acked = await notice_events(services)
    base = {"display_id": d.id, "connection_id": o.connection.id, "session_id": 2, "user": "CORP\\hong",
            "kind": "existing", "version": 0, "attempt": 1}
    assert {k: shown[k] for k in base} == base and "elapsed_ms" not in shown
    assert {k: acked[k] for k in base} == base and acked["elapsed_ms"] == 1000
    assert d.user == "CORP\\hong"

async def test_open_records_first_and_last_shown_per_attempt(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    d = services.displays.pending_for_session(2)
    first_at = clock.now()
    services.displays.open(services.displays.issue(d.id).token, peer_session=2)
    clock.advance(30)
    tk2 = services.displays.issue(d.id)
    services.displays.open(tk2.token, peer_session=2)
    got = services.displays.get(d.id)
    assert (got.first_shown_at, got.last_shown_at, got.attempts) == (first_at, clock.now(), 2)
    clock.advance(2)
    assert services.displays.acknowledge(tk2.token, peer_session=2).ack_ms == 2000  # from the last showing
    assert [e["attempt"] for e in await notice_events(services) if e["event"] == "notice_shown"] == [1, 2]

async def test_ack_without_open_counts_zero_ms(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    tk = services.displays.issue(services.displays.pending_for_session(2).id)
    clock.advance(5)
    d = services.displays.acknowledge(tk.token, peer_session=2)
    assert (d.ack_ms, d.acknowledged_at, d.first_shown_at) == (0, clock.now(), None)

async def test_closed_display_tokens_are_refused_without_a_tamper_report(services, clock):
    t = services.rdp; t.apply(snap(clock.now()))
    t.apply(snap(clock.now(), ws(2)))
    d = services.displays.pending_for_session(2)
    tk = services.displays.issue(d.id)
    t.apply(snap(clock.now()))  # logoff closes the display
    for call in (services.displays.open, services.displays.acknowledge):
        with pytest.raises(DisplayNotFoundError):
            call(tk.token, peer_session=2)
    with pytest.raises(DisplayNotFoundError):
        services.displays.issue(d.id)
    with pytest.raises(DisplayNotFoundError):
        services.displays.issue(999)
    assert services.tamper.recent(10) == []

async def test_acknowledged_display_cannot_be_opened_and_idempotent_ack_checks_the_session(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    tk = services.displays.issue(services.displays.pending_for_session(2).id)
    services.displays.acknowledge(tk.token, peer_session=2)
    with pytest.raises(DisplayNotFoundError):
        services.displays.open(tk.token, peer_session=2)
    with pytest.raises(DisplayNotFoundError):
        services.displays.acknowledge(tk.token, peer_session=5)
    assert [r["peer_session"] for r in services.tamper.recent(10)] == [5]

async def test_unacknowledged_on_a_closed_display_logs_nothing(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    d = services.displays.pending_for_session(2)
    services.displays.acknowledge(services.displays.issue(d.id).token, peer_session=2)
    services.displays.unacknowledged(d.id, "agent_exited")
    services.displays.unacknowledged(999, "agent_exited")
    assert [e["event"] for e in await notice_events(services)] == ["notice_acknowledged"]

async def test_listeners_hear_created_and_acknowledged(services, clock):
    heard = []
    services.displays.add_listener(lambda what, d: heard.append((what, d.id, d.closed_reason)))
    services.rdp.apply(snap(clock.now(), ws(2)))
    d = services.displays.pending_for_session(2)
    tk = services.displays.issue(d.id)
    services.displays.acknowledge(tk.token, peer_session=2)
    services.displays.acknowledge(tk.token, peer_session=2)  # idempotent: no second notification
    assert heard == [("created", d.id, None), ("acknowledged", d.id, "acknowledged")]

async def test_display_listener_runs_before_later_tracker_listeners(services, clock):
    seen = []
    def later(change):
        d = services.displays.pending_for_session(change.session.session_id)
        seen.append(d.connection_id == change.connection.id)
    services.rdp.add_listener(later)
    services.rdp.apply(snap(clock.now(), ws(2)))
    assert seen == [True]

async def test_latest_for_connections_picks_the_newest_display(services, clock):
    t = services.rdp; t.apply(snap(clock.now()))
    [o1] = t.apply(snap(clock.now(), ws(2)))
    [o2] = t.apply(snap(clock.now(), ws(2), ws(3, user="kim", ip="10.0.3.22", name="KIM-PC")))
    again = services.displays.create(o1.connection)
    latest = services.displays.latest_for_connections([o1.connection.id, o2.connection.id, 12345])
    assert set(latest) == {o1.connection.id, o2.connection.id}
    assert latest[o1.connection.id].id == again.id
    assert services.displays.latest_for_connections([]) == {}

async def test_board_ack_state_follows_the_new_connection(services, clock):
    t = services.rdp; t.apply(snap(clock.now()))
    t.apply(snap(clock.now(), ws(2)))
    d = services.displays.pending_for_session(2)
    services.displays.acknowledge(services.displays.issue(d.id).token, peer_session=2)
    assert t.board_sessions()[0]["notice_acknowledged"] is True
    clock.advance(5); t.apply(snap(clock.now(), ws(2, connected=clock.now())))  # fast reconnect
    assert t.board_sessions()[0]["notice_acknowledged"] is False
    assert services.displays.pending_for_session(2).kind == "reconnect"

async def test_start_closes_every_open_display_once(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2), ws(3, user="kim")))
    assert services.displays.start() == 2
    assert services.displays.pending_for_session(2) is None and services.displays.pending_for_session(3) is None
    reasons = [e["reason"] for e in await notice_events(services) if e["event"] == "notice_unacknowledged"]
    assert reasons == ["service_restart", "service_restart"]
    assert services.displays.start() == 0


async def test_without_a_session_source_a_previous_runs_displays_still_close_at_start(services, clock):
    """M12: ``--session-source none`` must not leave the last run's open displays open forever."""
    from tests.winfakes import eventually
    services.rdp.apply(snap(clock.now(), ws(2)))
    d = services.displays.pending_for_session(2)
    assert services.config_collectors.wts is None
    await services.collectors.start()
    try:
        await eventually(lambda: services.displays.get(d.id).closed_reason == "service_restart")
    finally:
        await services.collectors.stop()
