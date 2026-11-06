import os
import threading
import time

from mcp_agent import VERSION
from mcp_agent.client import ServerClient
from mcp_agent.config import AgentConfig
from mcp_agent.dialog import PrintWindow
from mcp_agent.runner import AgentRunner


def cfg(server, tmp_path, **kw):
    base = dict(server=server, token="tok", dialog="print", url_file=tmp_path / "u.url", edge_path=None,
                profile_dir=tmp_path / "p", unreachable_exit_sec=120.0)
    base.update(kw); return AgentConfig(**base)

class FakeWindow:
    def __init__(self):
        self.opened, self.closed, self.user_closed = [], 0, False
    def open(self, url, display_id):
        self.opened.append((display_id, url)); self.user_closed = False
    def close(self):
        self.closed += 1
    def closed_by_user(self):
        return self.user_closed

def wait_until(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < end, "condition not met"
        time.sleep(0.02)

def test_runner_shows_and_closes_notice(fake_server, tmp_path):
    url = "http://127.0.0.1:8700/notice#d=7&t=x"
    fake_server.commands.extend([{"type": "show_notice", "display_id": 7, "attempt": 1, "url": url},
                                 {"type": "close_notice", "display_id": 7}, {"type": "exit"}])
    c = cfg(fake_server.url, tmp_path)
    code = AgentRunner(c, ServerClient(fake_server.url, "tok"), PrintWindow(c.url_file), session_id=2, pid=os.getpid(), idle=lambda: 3.7).run()
    assert code == 0 and c.url_file.read_text("utf-8").splitlines() == [f"OPEN 7 {url}", "CLOSE 7"]
    hello = next(r for r in fake_server.requests if r[1] == "/api/agent/hello")
    assert hello[2] == {"session_id": 2, "pid": os.getpid(), "version": VERSION}

def test_runner_reports_a_window_the_user_closed(fake_server, tmp_path):
    w = FakeWindow(); fake_server.commands.append({"type": "show_notice", "display_id": 7, "attempt": 1, "url": "u"})
    r = AgentRunner(cfg(fake_server.url, tmp_path), ServerClient(fake_server.url, "tok"), w, session_id=2, pid=1, idle=lambda: 0)
    result = []; t = threading.Thread(target=lambda: result.append(r.run())); t.start()
    wait_until(lambda: w.opened == [(7, "u")])
    w.user_closed = True
    wait_until(lambda: any(x[:2] == ("POST", "/api/agent/notice/7/closed") for x in fake_server.requests))
    fake_server.commands.append({"type": "exit"}); t.join(10)
    assert result == [0]

def test_runner_sends_heartbeats_with_idle(fake_server, tmp_path):
    fake_server.hello_body = {"heartbeat_sec": 0.05, "events_max": 200, "idle_threshold_sec": 300}
    r = AgentRunner(cfg(fake_server.url, tmp_path), ServerClient(fake_server.url, "tok"), FakeWindow(), session_id=2, pid=1, idle=lambda: 12.9)
    t = threading.Thread(target=r.run); t.start()
    wait_until(lambda: sum(1 for x in fake_server.requests if x[1] == "/api/agent/heartbeat") >= 2)
    fake_server.commands.append({"type": "exit"}); t.join(10)
    hb = next(x for x in fake_server.requests if x[1] == "/api/agent/heartbeat")
    assert hb[2] == {"idle_sec": 12, "locked": None}

def test_runner_exits_3_when_rejected(fake_server, tmp_path):
    fake_server.status_for["/api/agent/hello"] = 401
    assert AgentRunner(cfg(fake_server.url, tmp_path), ServerClient(fake_server.url, "tok"), FakeWindow(), session_id=2, pid=1).run() == 3

def test_runner_exits_4_after_the_unreachable_limit(tmp_path):
    now = [0.0]
    r = AgentRunner(cfg("http://127.0.0.1:9", tmp_path, unreachable_exit_sec=30.0), ServerClient("http://127.0.0.1:9", "t", timeout=0.2),
                    FakeWindow(), session_id=2, pid=1, monotonic=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
    assert r.run() == 4 and now[0] >= 30


# --- beyond the plan ---------------------------------------------------------------------------

from mcp_agent.runner import wants_window_events  # noqa: E402


class FlakyClock:
    """Fake monotonic clock; ``sleep`` advances it and records the delay."""
    def __init__(self):
        self.now, self.sleeps, self.on_sleep = 0.0, [], None
    def monotonic(self):
        return self.now
    def sleep(self, s):
        self.sleeps.append(s); self.now += s
        if self.on_sleep:
            self.on_sleep(len(self.sleeps))


def lines(c):
    return c.url_file.read_text("utf-8").splitlines()


def test_unreachable_backoff_is_1_2_4_8_then_10(tmp_path):
    clock = FlakyClock()
    r = AgentRunner(cfg("http://127.0.0.1:9", tmp_path, unreachable_exit_sec=30.0), ServerClient("http://127.0.0.1:9", "t", timeout=0.2),
                    FakeWindow(), session_id=2, pid=1, monotonic=clock.monotonic, sleep=clock.sleep)
    assert r.run() == 4 and clock.sleeps == [1, 2, 4, 8, 10, 10]


def test_hello_retries_until_the_server_answers(fake_server, tmp_path):
    fake_server.status_for["/api/agent/hello"] = 503
    fake_server.commands.append({"type": "exit"})
    clock = FlakyClock()
    clock.on_sleep = lambda n: fake_server.status_for.pop("/api/agent/hello") if n == 2 else None
    hellos = []
    r = AgentRunner(cfg(fake_server.url, tmp_path), ServerClient(fake_server.url, "tok"), FakeWindow(), session_id=2, pid=1,
                    monotonic=clock.monotonic, sleep=clock.sleep, on_hello=hellos.append)
    assert r.run() == 0 and clock.sleeps == [1, 2] and hellos == [fake_server.hello_body]
    assert sum(1 for x in fake_server.requests if x[1] == "/api/agent/hello") == 3


def test_window_events_flag_defaults_to_on():
    assert wants_window_events({"heartbeat_sec": 5}) is True
    assert wants_window_events({"window_events": True}) is True
    assert wants_window_events({"window_events": False}) is False


def test_a_new_notice_replaces_the_open_one_and_exit_closes_it(fake_server, tmp_path):
    fake_server.commands.extend([{"type": "show_notice", "display_id": 7, "attempt": 1, "url": "http://a"},
                                 {"type": "close_notice", "display_id": 99},
                                 {"type": "reboot"},
                                 {"type": "show_notice", "display_id": 8, "attempt": 1, "url": "http://b"},
                                 {"type": "exit"}])
    c = cfg(fake_server.url, tmp_path)
    assert AgentRunner(c, ServerClient(fake_server.url, "tok"), PrintWindow(c.url_file), session_id=2, pid=1, idle=lambda: 0).run() == 0
    assert lines(c) == ["OPEN 7 http://a", "CLOSE 7", "OPEN 8 http://b", "CLOSE 8"]


def test_rejected_during_the_loop_closes_the_window_and_exits_3(fake_server, tmp_path):
    w = FakeWindow()
    fake_server.commands.append({"type": "show_notice", "display_id": 7, "attempt": 1, "url": "u"})
    original_open = w.open
    def open_then_revoke(url, display_id):
        original_open(url, display_id); fake_server.status_for["/api/agent/next"] = 403
    w.open = open_then_revoke
    r = AgentRunner(cfg(fake_server.url, tmp_path), ServerClient(fake_server.url, "tok"), w, session_id=2, pid=1, idle=lambda: 0)
    assert r.run() == 3 and w.opened == [(7, "u")] and w.closed >= 1


def test_a_rejected_heartbeat_stops_the_loop_with_3(fake_server, tmp_path):
    fake_server.hello_body = {**fake_server.hello_body, "heartbeat_sec": 0.05}
    fake_server.status_for["/api/agent/heartbeat"] = 401
    w = FakeWindow()
    r = AgentRunner(cfg(fake_server.url, tmp_path), ServerClient(fake_server.url, "tok"), w, session_id=2, pid=1, idle=lambda: 0)
    result = []; t = threading.Thread(target=lambda: result.append(r.run())); t.start(); t.join(10)
    assert result == [3] and w.closed >= 1


def test_loop_outage_backs_off_then_recovers(fake_server, tmp_path):
    w = FakeWindow(); clock = FlakyClock()
    fake_server.commands.append({"type": "show_notice", "display_id": 7, "attempt": 1, "url": "u"})
    original_open = w.open
    def open_then_outage(url, display_id):
        original_open(url, display_id); fake_server.status_for["/api/agent/next"] = 503
    w.open = open_then_outage
    def recover(n):
        if n == 3:
            fake_server.status_for.pop("/api/agent/next"); fake_server.commands.append({"type": "exit"})
    clock.on_sleep = recover
    r = AgentRunner(cfg(fake_server.url, tmp_path), ServerClient(fake_server.url, "tok"), w, session_id=2, pid=1, idle=lambda: 0,
                    monotonic=clock.monotonic, sleep=clock.sleep)
    assert r.run() == 0 and clock.sleeps == [1, 2, 4] and w.opened == [(7, "u")]


def test_loop_outage_past_the_limit_closes_the_window_and_exits_4(fake_server, tmp_path):
    w = FakeWindow(); clock = FlakyClock()
    fake_server.commands.append({"type": "show_notice", "display_id": 7, "attempt": 1, "url": "u"})
    original_open = w.open
    def open_then_outage(url, display_id):
        original_open(url, display_id); fake_server.status_for["/api/agent/next"] = 503
    w.open = open_then_outage
    r = AgentRunner(cfg(fake_server.url, tmp_path, unreachable_exit_sec=10.0), ServerClient(fake_server.url, "tok"), w, session_id=2,
                    pid=1, idle=lambda: 0, monotonic=clock.monotonic, sleep=clock.sleep)
    assert r.run() == 4 and clock.sleeps == [1, 2, 4, 8] and w.closed >= 1


def test_a_closed_report_lost_to_an_outage_is_sent_again(fake_server, tmp_path):
    w = FakeWindow(); clock = FlakyClock()
    fake_server.commands.append({"type": "show_notice", "display_id": 7, "attempt": 1, "url": "u"})
    original_open = w.open
    def open_then_user_closes(url, display_id):
        original_open(url, display_id); w.user_closed = True
        fake_server.status_for["/api/agent/notice/7/closed"] = 503
    w.open = open_then_user_closes
    def recover(n):
        fake_server.status_for.pop("/api/agent/notice/7/closed", None); fake_server.commands.append({"type": "exit"})
    clock.on_sleep = recover
    r = AgentRunner(cfg(fake_server.url, tmp_path), ServerClient(fake_server.url, "tok"), w, session_id=2, pid=1, idle=lambda: 0,
                    monotonic=clock.monotonic, sleep=clock.sleep)
    assert r.run() == 0
    closed = [x for x in fake_server.requests if x[1] == "/api/agent/notice/7/closed"]
    assert len(closed) == 2 and clock.sleeps == [1]


def test_an_unexpected_error_still_closes_the_window(fake_server, tmp_path):
    w = FakeWindow()
    fake_server.commands.append({"type": "show_notice", "display_id": 7, "attempt": 1, "url": "u"})
    original_open = w.open
    def open_then_bad_request(url, display_id):
        original_open(url, display_id); fake_server.status_for["/api/agent/next"] = 422
    w.open = open_then_bad_request
    r = AgentRunner(cfg(fake_server.url, tmp_path), ServerClient(fake_server.url, "tok"), w, session_id=2, pid=1, idle=lambda: 0)
    try:
        r.run()
    except RuntimeError as e:
        assert "422" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
    assert w.closed >= 1


def test_main_runs_the_print_agent_and_drops_the_token(fake_server, tmp_path, monkeypatch):
    from mcp_agent.__main__ import main
    from mcp_agent.win32 import current_session_id
    url_file = tmp_path / "agent-1.url"
    fake_server.commands.extend([{"type": "show_notice", "display_id": 3, "attempt": 1, "url": "http://n"}, {"type": "exit"}])
    monkeypatch.setenv("MCPMON_AGENT_TOKEN", "secret")
    assert main(["--server", fake_server.url + "/", "--dialog", "print", "--url-file", str(url_file)]) == 0
    assert "MCPMON_AGENT_TOKEN" not in os.environ
    assert url_file.read_text("utf-8").splitlines() == ["OPEN 3 http://n", "CLOSE 3"]
    hello = next(r for r in fake_server.requests if r[1] == "/api/agent/hello")
    assert hello[2] == {"session_id": current_session_id(), "pid": os.getpid(), "version": VERSION}
    assert all(r[3]["X-Agent-Token"] == "secret" for r in fake_server.requests)
