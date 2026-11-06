import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mcp_agent.client import ServerUnavailable
from mcp_agent.coalesce import RawWinEvent, WindowEventCoalescer
from mcp_agent.idle import IdleTracker
from mcp_agent.pump import EventPump
from mcp_agent.sender import EventSender, to_payload

AT = datetime(2026, 11, 4, 4, 59, 57, tzinfo=UTC)  # 13:59:57 KST

def raw(t, kind="foreground", hwnd=1, title="A", pid=10, exe="a.exe"):
    return RawWinEvent(t, kind, hwnd, pid, exe, title, AT + timedelta(seconds=t))

def test_foreground_burst_keeps_the_last():
    c = WindowEventCoalescer()
    c.add(raw(0.0, hwnd=1, title="A")); c.add(raw(0.1, hwnd=2, title="B")); c.add(raw(0.2, hwnd=3, title="C"))
    assert c.drain(0.4) == [] and [e.title for e in c.drain(0.5)] == ["C"]

def test_refocusing_the_same_window_and_title_is_dropped():
    c = WindowEventCoalescer(); c.add(raw(0, hwnd=1, title="A")); assert len(c.drain(1)) == 1
    c.add(raw(2, hwnd=1, title="A")); assert c.drain(3) == []
    c.add(raw(4, hwnd=1, title="A2")); assert [e.title for e in c.drain(5)] == ["A2"]

def test_title_changes_merge_for_the_foreground_window_only():
    c = WindowEventCoalescer(); c.add(raw(0, hwnd=1, title="doc")); c.drain(1)
    for i, t in enumerate(["doc*", "doc**", "doc***"]):
        c.add(raw(1 + i * 0.2, kind="title", hwnd=1, title=t))
    c.add(raw(1.1, kind="title", hwnd=9, title="background"))
    assert c.drain(2.3) == []
    assert [(e.kind, e.title) for e in c.drain(2.4)] == [("title", "doc***")]

def test_minimize_restore_pass_through_with_dedupe_and_order():
    c = WindowEventCoalescer(); c.add(raw(0, hwnd=1, title="A"))
    c.add(raw(0.5, kind="minimize", hwnd=1)); c.add(raw(0.6, kind="minimize", hwnd=1)); c.add(raw(0.9, kind="restore", hwnd=1))
    assert [e.kind for e in c.drain(1)] == ["foreground", "minimize", "restore"]

def test_idle_transitions():
    i = IdleTracker(threshold_sec=300)
    assert i.update(10, AT) is None and i.update(299, AT) is None
    assert i.update(300, AT) == {"type": "idle", "at": "2026-11-04T13:59:57.000+09:00", "idle_sec": 300}
    assert i.update(420, AT) is None
    assert i.update(2, AT) == {"type": "active", "at": "2026-11-04T13:59:57.000+09:00", "idle_sec": 420}
    assert i.update(5, AT) is None

def test_payload_matches_the_server_fixture():
    fixture = Path(__file__).resolve().parents[2] / "server" / "tests" / "fixtures" / "agent-events.json"
    exe = r"C:\Windows\System32\notepad.exe"
    items = [RawWinEvent(0.0, "foreground", 1, 4321, exe, "메모 - 메모장", AT),
             RawWinEvent(1.5, "title", 1, 4321, exe, "*메모 - 메모장", AT + timedelta(seconds=1.5)),
             RawWinEvent(2.0, "minimize", 1, 4321, exe, "*메모 - 메모장", AT + timedelta(seconds=2)),
             {"type": "idle", "at": "2026-11-04T14:00:00.000+09:00", "idle_sec": 300}]
    assert to_payload(items) == json.loads(fixture.read_text("utf-8"))

class FakeClient:
    def __init__(self, fail=0):
        self.fail, self.posts = fail, []
    def post(self, path, body=None, *, verified_only=False):
        if self.fail:
            self.fail -= 1; raise ServerUnavailable("down")
        self.posts.append((path, [e["idle_sec"] for e in body["events"]]))

def test_sender_batches_and_buffers_while_unavailable():
    client = FakeClient(fail=1); s = EventSender(client, events_max=2, buffer_max=3)
    for n in range(4):
        s.add({"type": "idle", "at": "2026-11-04T14:00:00.000+09:00", "idle_sec": n})
    s.flush()
    assert client.posts == [] and (s.pending, s.dropped) == (3, 1)
    s.flush()
    assert client.posts == [("/api/agent/events", [1, 2]), ("/api/agent/events", [3])] and s.pending == 0

def test_pump_moves_coalesced_events_and_idle_into_the_sender():
    sent = []
    class S:
        def add(self, item): sent.append(item)
    pump = EventPump(WindowEventCoalescer(), S(), IdleTracker(300), idle_seconds=lambda: 301, idle_every_sec=5)
    pump.on_raw(raw(0.0, title="A"))
    pump.step(0.1, AT)
    assert [x["type"] for x in sent] == ["idle"]
    pump.step(0.5, AT)
    assert [getattr(x, "kind", None) or x["type"] for x in sent] == ["idle", "foreground"]


# --- beyond the plan ---------------------------------------------------------------------------

import threading  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402

from mcp_agent.client import AgentRejected  # noqa: E402
from mcp_agent.sender import iso, to_event  # noqa: E402


def test_foreground_switches_further_apart_than_the_merge_window_are_all_kept():
    c = WindowEventCoalescer()
    c.add(raw(0.0, hwnd=1, title="A")); c.add(raw(0.5, hwnd=2, title="B"))
    assert [e.title for e in c.drain(0.6)] == ["A"]
    assert [e.title for e in c.drain(0.8)] == ["B"]


def test_a_title_equal_to_the_last_one_sent_for_that_window_is_dropped():
    c = WindowEventCoalescer(); c.add(raw(0, hwnd=1, title="doc")); c.drain(1)
    c.add(raw(2, kind="title", hwnd=1, title="doc"))
    assert c.drain(4) == []
    c.add(raw(5, kind="title", hwnd=1, title="doc*")); c.add(raw(5.5, kind="title", hwnd=1, title="doc"))
    assert c.drain(7) == []  # merged back to the title already sent


def test_title_of_a_window_that_lost_the_foreground_is_dropped():
    c = WindowEventCoalescer(); c.add(raw(0, hwnd=1, title="one")); c.add(raw(1, hwnd=2, title="two"))
    c.add(raw(1.1, kind="title", hwnd=1, title="one*"))
    assert [(e.kind, e.title) for e in c.drain(5)] == [("foreground", "one"), ("foreground", "two")]


def test_minimize_dedupe_is_per_window_and_expires():
    c = WindowEventCoalescer()
    c.add(raw(0.0, kind="minimize", hwnd=1)); c.add(raw(0.1, kind="minimize", hwnd=2))
    c.add(raw(0.2, kind="restore", hwnd=1)); c.add(raw(0.4, kind="minimize", hwnd=1))
    assert [(e.kind, e.hwnd) for e in c.drain(0.4)] == [("minimize", 1), ("minimize", 2), ("restore", 1), ("minimize", 1)]


def test_idle_accepts_float_seconds_and_reports_ints_in_kst():
    i = IdleTracker(threshold_sec=300)
    at = datetime(2026, 11, 4, 15, 0, 0, 123456, tzinfo=UTC)
    assert i.update(300.9, at) == {"type": "idle", "at": "2026-11-05T00:00:00.123+09:00", "idle_sec": 300}
    assert i.update(310.7, at) is None
    assert i.update(0.2, at) == {"type": "active", "at": "2026-11-05T00:00:00.123+09:00", "idle_sec": 310}
    assert iso(at) == "2026-11-05T00:00:00.123+09:00"


def test_to_event_fits_the_server_limits_and_utf8():
    e = RawWinEvent(0.0, "title", 1, 7, "x" * 300, "a\ud800b" + "t" * 600, AT)
    ev = to_event(e)
    assert ev["type"] == "title" and ev["pid"] == 7 and ev["at"] == "2026-11-04T13:59:57.000+09:00"
    assert len(ev["title"]) == 512 and ev["title"].startswith("a?b") and len(ev["exe"]) == 260
    json.dumps(ev, ensure_ascii=False).encode("utf-8")  # no lone surrogate left
    assert to_event(RawWinEvent(0.0, "restore", 1, 7, None, "", AT))["exe"] is None


class RecordingClient:
    def __init__(self, raise_with=None):
        self.raise_with, self.posts = raise_with, []
    def post(self, path, body=None, *, verified_only=False):
        self.posts.append((path, body))
        if self.raise_with is not None:
            raise self.raise_with


def test_sender_drops_a_batch_the_server_refuses_instead_of_retrying_it_forever(capsys):
    client = RecordingClient(RuntimeError("POST /api/agent/events: unexpected status 422"))
    s = EventSender(client, events_max=2)
    for n in range(3):
        s.add({"type": "idle", "at": "2026-11-04T14:00:00.000+09:00", "idle_sec": n})
    s.flush()
    assert len(client.posts) == 2 and (s.pending, s.dropped) == (0, 3)
    assert "422" in capsys.readouterr().err


def test_sender_lets_a_rejected_token_through_and_keeps_the_events():
    s = EventSender(RecordingClient(AgentRejected("401")))
    s.add(raw(0.0))
    with pytest.raises(AgentRejected):
        s.flush()
    assert s.pending == 1 and s.dropped == 0


def test_sender_posts_window_events_in_the_server_shape():
    client = RecordingClient(); s = EventSender(client)
    s.add(raw(0.0, title="A", pid=10, exe="a.exe"))
    s.flush(); s.flush()
    assert client.posts == [("/api/agent/events", {"events": [
        {"type": "foreground", "at": "2026-11-04T13:59:57.000+09:00", "pid": 10, "exe": "a.exe", "title": "A"}]})]


def test_pump_checks_idle_every_idle_every_sec_and_survives_a_failing_idle_source():
    sent, values = [], [10.0, OSError("no input info"), 301.0, 2.0]
    def idle_seconds():
        v = values.pop(0)
        if isinstance(v, Exception):
            raise v
        return v
    class S:
        def add(self, item): sent.append(item)
    pump = EventPump(WindowEventCoalescer(), S(), IdleTracker(300), idle_seconds=idle_seconds, idle_every_sec=5)
    for mono in (0.0, 1.0, 4.9, 5.0, 9.9, 10.0, 15.0):
        pump.step(mono, AT)
    assert [x["type"] for x in sent] == ["idle", "active"] and values == []


def test_pump_run_steps_and_flushes_until_stopped():
    flushed = threading.Event()
    class S:
        def __init__(self): self.items = []
        def add(self, item): self.items.append(item)
        def flush(self):
            if self.items: flushed.set()
    s = S(); pump = EventPump(WindowEventCoalescer(), s, IdleTracker(300), idle_seconds=lambda: 0.0)
    stop = threading.Event(); t = threading.Thread(target=pump.run, args=(stop,)); t.start()
    try:
        pump.on_raw(RawWinEvent(time.monotonic(), "foreground", 1, 10, "a.exe", "A", AT))
        assert flushed.wait(5)
    finally:
        stop.set(); t.join(5)
    assert not t.is_alive() and [e.title for e in s.items] == ["A"]


def test_pump_run_ends_when_the_token_is_rejected():
    class S:
        def add(self, item): pass
        def flush(self): raise AgentRejected("403")
    pump = EventPump(WindowEventCoalescer(), S(), IdleTracker(300), idle_seconds=lambda: 0.0)
    t = threading.Thread(target=pump.run, args=(threading.Event(),)); t.start(); t.join(5)
    assert not t.is_alive()


def test_pump_run_keeps_going_after_an_unexpected_flush_error(capsys):
    calls = []
    class S:
        def add(self, item): pass
        def flush(self):
            calls.append(1)
            if len(calls) == 1:
                raise ValueError("boom")
    pump = EventPump(WindowEventCoalescer(), S(), IdleTracker(300), idle_seconds=lambda: 0.0)
    stop = threading.Event(); t = threading.Thread(target=pump.run, args=(stop,)); t.start()
    try:
        deadline = time.monotonic() + 5
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        stop.set(); t.join(5)
    assert len(calls) >= 2 and "boom" in capsys.readouterr().err


# --- __main__: the window activity started on hello --------------------------------------------

from mcp_agent.__main__ import WindowActivity  # noqa: E402
from mcp_agent.client import ServerClient  # noqa: E402
from tests.fake_server import KEY  # noqa: E402


class FakeHooks:
    made = []
    def __init__(self, on_event):
        self.on_event, self.started, self.stopped = on_event, False, False
        FakeHooks.made.append(self)
    def start(self): self.started = True
    def stop(self): self.stopped = True


def test_activity_skips_hooks_when_the_server_does_not_want_window_events(fake_server):
    FakeHooks.made = []
    a = WindowActivity(ServerClient(fake_server.url, "tok", KEY), hook_factory=FakeHooks, idle_seconds=lambda: 999.0)
    a.on_hello({"heartbeat_sec": 5, "events_max": 200, "idle_threshold_sec": 300, "window_events": False})
    a.stop()
    assert FakeHooks.made == [] and a.pump is None
    assert not any(r[1] == "/api/agent/events" for r in fake_server.requests)


def verified_client(fake_server):
    """A client that has had a proven answer (in the agent: the hello)."""
    client = ServerClient(fake_server.url, "tok", KEY)
    client.next(0)
    return client


def test_activity_runs_hooks_and_pump_and_flushes_on_stop(fake_server):
    FakeHooks.made = []
    a = WindowActivity(verified_client(fake_server), hook_factory=FakeHooks, idle_seconds=lambda: 999.0)
    a.on_hello({"heartbeat_sec": 5, "events_max": 200, "idle_threshold_sec": 300})  # missing key = on
    try:
        (hooks,) = FakeHooks.made
        assert hooks.started and a.pump is not None
        hooks.on_event(RawWinEvent(time.monotonic(), "foreground", 1, 10, "a.exe", "A", AT))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            sent = [e for r in fake_server.requests if r[1] == "/api/agent/events" for e in r[2]["events"]]
            if {e["type"] for e in sent} >= {"idle", "foreground"}:
                break
            time.sleep(0.05)
    finally:
        a.stop()
    assert hooks.stopped and not a.running
    sent = [e for r in fake_server.requests if r[1] == "/api/agent/events" for e in r[2]["events"]]
    assert [e["type"] for e in sent] == ["idle", "foreground"]
    assert sent[1] == {"type": "foreground", "at": "2026-11-04T13:59:57.000+09:00", "pid": 10, "exe": "a.exe", "title": "A"}


def test_activity_final_flush_sends_what_the_pump_left(fake_server):
    FakeHooks.made = []
    client = verified_client(fake_server)
    a = WindowActivity(client, hook_factory=FakeHooks, idle_seconds=lambda: 999.0)
    fake_server.status_for["/api/agent/events"] = 503  # the pump cannot deliver
    a.on_hello({"events_max": 200, "idle_threshold_sec": 300, "window_events": True})
    deadline = time.monotonic() + 5
    while not any(r[1] == "/api/agent/events" for r in fake_server.requests) and time.monotonic() < deadline:
        time.sleep(0.05)
    del fake_server.status_for["/api/agent/events"]
    client.next(0)  # the runner's long poll proves the server again after the outage
    a.stop()
    last = [r for r in fake_server.requests if r[1] == "/api/agent/events"][-1]
    assert [e["type"] for e in last[2]["events"]] == ["idle"]


def test_sender_posts_window_events_only_to_a_verified_server():
    """I1: the event batch asks the client to send only after a proven answer."""
    seen = []
    class Client:
        def post(self, path, body=None, *, verified_only=False):
            seen.append((path, verified_only))
    s = EventSender(Client())
    s.add({"type": "idle", "at": "2026-11-04T14:00:00.000+09:00", "idle_sec": 1}); s.flush()
    assert seen == [("/api/agent/events", True)]


def test_activity_final_flush_sends_nothing_after_an_unproven_401(fake_server):
    """R2: a squatter's 401 makes the agent stop; the final flush must not hand it the window titles."""
    FakeHooks.made = []
    client = verified_client(fake_server)
    fake_server.server_key = None
    fake_server.status_for["/api/agent/heartbeat"] = 401
    with pytest.raises(AgentRejected):
        client.post("/api/agent/heartbeat", {})
    a = WindowActivity(client, hook_factory=FakeHooks, idle_seconds=lambda: 999.0)
    a.on_hello({"events_max": 200, "idle_threshold_sec": 300, "window_events": True})
    deadline = time.monotonic() + 5
    while (a._sender is None or a._sender.pending == 0) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert a._sender is not None and a._sender.pending > 0
    a.stop()
    assert not any(r[1] == "/api/agent/events" for r in fake_server.requests)


# --- M13 (Plan 5 Task 9): the dropped count reaches the server ---------------------------------

class CountingClient:
    """Records each posted body; ``outcomes`` (an exception or None per post) are used in order."""
    def __init__(self, *outcomes):
        self.outcomes, self.bodies = list(outcomes), []
    def post(self, path, body=None, *, verified_only=False):
        self.bodies.append(body)
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome is not None:
            raise outcome

def idle(n):
    return {"type": "idle", "at": "2026-11-04T14:00:00.000+09:00", "idle_sec": n}

def test_overflow_drops_ride_on_the_next_batch_once():
    client = CountingClient(); s = EventSender(client, events_max=2, buffer_max=2)
    for n in range(5):
        s.add(idle(n))
    s.flush()
    assert [b.get("dropped") for b in client.bodies] == [3] and s.dropped == 3
    s.add(idle(9)); s.flush()
    assert "dropped" not in client.bodies[1]  # reported once

def test_dropped_count_waits_while_the_server_is_unavailable():
    client = CountingClient(ServerUnavailable("down")); s = EventSender(client, events_max=5, buffer_max=1)
    s.add(idle(0)); s.add(idle(1)); s.flush()
    assert client.bodies[0]["dropped"] == 1
    s.flush()
    assert client.bodies[1] == {"events": [idle(1)], "dropped": 1}

def test_a_refused_batch_is_counted_in_the_next_report(capsys):
    client = CountingClient(RuntimeError("POST /api/agent/events: unexpected status 422"))
    s = EventSender(client, events_max=1)
    s.add(idle(0)); s.add(idle(1)); s.flush()
    assert [b.get("dropped") for b in client.bodies] == [None, 1] and s.dropped == 1
    s.add(idle(2)); s.flush()
    assert "dropped" not in client.bodies[2]
    assert "dropped 1 events" in capsys.readouterr().err

def test_payload_has_no_dropped_key_when_nothing_was_dropped():
    assert to_payload([idle(1)]) == {"events": [idle(1)]}
    assert to_payload([idle(1)], dropped=0) == {"events": [idle(1)]}
    assert to_payload([idle(1)], dropped=4) == {"events": [idle(1)], "dropped": 4}
