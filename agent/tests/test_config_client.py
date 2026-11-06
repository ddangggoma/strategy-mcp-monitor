import socket
from pathlib import Path

import pytest

from mcp_agent.client import AgentRejected, ServerClient, ServerUnavailable, ServerUnverified
from mcp_agent.config import parse_args
from tests.fake_server import KEY

E = {"MCPMON_AGENT_TOKEN": "t", "MCPMON_AGENT_SERVER_KEY": KEY}


def test_config_requires_token_and_server():
    with pytest.raises(SystemExit) as e:
        parse_args(["--server", "http://127.0.0.1:8700"], {})
    assert e.value.code == 2
    with pytest.raises(SystemExit):
        parse_args([], dict(E))

def test_config_reads_and_removes_the_token():
    env = {"MCPMON_AGENT_TOKEN": "tok", "MCPMON_AGENT_SERVER_KEY": KEY, "OTHER": "1"}
    cfg = parse_args(["--server", "http://127.0.0.1:8700/", "--dialog", "print", "--url-file", "u.url"], env)
    assert (cfg.server, cfg.token, cfg.dialog, cfg.url_file, cfg.unreachable_exit_sec) == ("http://127.0.0.1:8700", "tok", "print", Path("u.url"), 120)
    assert cfg.server_key == KEY
    assert "MCPMON_AGENT_TOKEN" not in env and "MCPMON_AGENT_SERVER_KEY" not in env and env["OTHER"] == "1"
    assert parse_args(["--server", "http://x"], dict(E)).dialog == "edge"

def test_client_sends_token_and_json(fake_server):
    c = ServerClient(fake_server.url, "tok", KEY)
    assert c.post("/api/agent/hello", {"session_id": 1, "title": "메모"}) == fake_server.hello_body
    method, path, body, headers = fake_server.requests[-1]
    assert (method, path, body, headers["X-Agent-Token"], headers["Content-Type"]) == \
        ("POST", "/api/agent/hello", {"session_id": 1, "title": "메모"}, "tok", "application/json")

def test_client_maps_statuses(fake_server):
    c = ServerClient(fake_server.url, "tok", KEY)
    assert c.next(0.05) is None and c.post("/api/agent/heartbeat", {"idle_sec": 1}) is None
    fake_server.status_for["/api/agent/heartbeat"] = 403
    with pytest.raises(AgentRejected):
        c.post("/api/agent/heartbeat", {})
    fake_server.status_for["/api/agent/heartbeat"] = 503
    with pytest.raises(ServerUnavailable):
        c.post("/api/agent/heartbeat", {})

def test_client_unavailable_when_nothing_listens():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    with pytest.raises(ServerUnavailable):
        ServerClient(f"http://127.0.0.1:{port}", "t", KEY, timeout=1).post("/api/agent/hello", {})

def test_agent_never_touches_the_database():
    src = "\n".join(p.read_text("utf-8") for p in (Path(__file__).parents[1] / "mcp_agent").glob("*.py"))
    assert "sqlite3" not in src and "config.db" not in src


# --- beyond the plan ---------------------------------------------------------------------------

def test_config_defaults_and_print_needs_a_url_file():
    cfg = parse_args(["--server", "http://127.0.0.1:8700"], {**E, "LOCALAPPDATA": r"C:\Users\u\AppData\Local"})
    assert (cfg.dialog, cfg.url_file, cfg.edge_path) == ("edge", None, None)
    assert cfg.profile_dir == Path(r"C:\Users\u\AppData\Local") / "mcp-monitor" / "notice-edge"
    assert isinstance(cfg.unreachable_exit_sec, float) and cfg.unreachable_exit_sec == 120.0
    cfg = parse_args(["--server", "http://x", "--edge-path", r"D:\e\msedge.exe", "--profile-dir", r"D:\p",
                      "--unreachable-exit-sec", "7.5"], dict(E))
    assert (cfg.edge_path, cfg.profile_dir, cfg.unreachable_exit_sec) == (r"D:\e\msedge.exe", Path(r"D:\p"), 7.5)
    env = dict(E)
    with pytest.raises(SystemExit) as e:
        parse_args(["--server", "http://x", "--dialog", "print"], env)
    assert e.value.code == 2 and "MCPMON_AGENT_TOKEN" not in env

def test_config_rejects_an_empty_token():
    with pytest.raises(SystemExit) as e:
        parse_args(["--server", "http://x"], {**E, "MCPMON_AGENT_TOKEN": ""})
    assert e.value.code == 2

def test_client_next_long_polls_with_the_timeout_and_returns_the_command(fake_server):
    fake_server.commands.append({"type": "exit"})
    c = ServerClient(fake_server.url, "tok", KEY)
    assert c.next(25.0) == {"type": "exit"}
    method, path, body, headers = fake_server.requests[-1]
    assert (method, path, body, headers["X-Agent-Token"]) == ("GET", "/api/agent/next", None, "tok")

def test_client_post_without_a_body(fake_server):
    assert ServerClient(fake_server.url, "tok", KEY).post("/api/agent/notice/7/closed") is None
    method, path, body, headers = fake_server.requests[-1]
    assert (method, path, body, headers["X-Agent-Token"]) == ("POST", "/api/agent/notice/7/closed", None, "tok")
    assert "Content-Type" not in headers

def test_client_maps_401_and_other_4xx(fake_server):
    c = ServerClient(fake_server.url, "tok", KEY)
    fake_server.status_for["/api/agent/next"] = 401
    with pytest.raises(AgentRejected):
        c.next(1)
    fake_server.status_for["/api/agent/next"] = 422
    with pytest.raises(RuntimeError) as e:
        c.next(1)
    assert not isinstance(e.value, (AgentRejected, ServerUnavailable)) and "422" in str(e.value)

def test_client_ignores_proxy_settings(fake_server, monkeypatch):
    # The service is on loopback: a proxy from the user's environment must never see the token.
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    assert ServerClient(fake_server.url, "tok", KEY).post("/api/agent/heartbeat", {"idle_sec": 1}) is None
    assert fake_server.requests[-1][1] == "/api/agent/heartbeat"

def test_client_read_timeout_is_unavailable():
    with socket.socket() as s:  # accepts the connection (backlog) but never answers
        s.bind(("127.0.0.1", 0)); s.listen(1); port = s.getsockname()[1]
        with pytest.raises(ServerUnavailable):
            ServerClient(f"http://127.0.0.1:{port}", "t", KEY, timeout=0.3).post("/api/agent/hello", {})


# --- I1 -------------------------------------------------------------------------------------

def test_config_requires_a_32_byte_hex_server_key_and_removes_it():
    for key in (None, "", "zz" * 32, "11" * 16):
        env = {"MCPMON_AGENT_TOKEN": "t"} if key is None else {"MCPMON_AGENT_TOKEN": "t", "MCPMON_AGENT_SERVER_KEY": key}
        with pytest.raises(SystemExit) as e:
            parse_args(["--server", "http://x"], env)
        assert e.value.code == 2 and "MCPMON_AGENT_SERVER_KEY" not in env and "MCPMON_AGENT_TOKEN" not in env

def test_client_sends_a_fresh_nonce_and_needs_the_proof(fake_server):
    c = ServerClient(fake_server.url, "tok", KEY)
    assert not c.verified
    c.post("/api/agent/heartbeat", {}); c.post("/api/agent/heartbeat", {})
    nonces = [r[3]["X-Agent-Nonce"] for r in fake_server.requests]
    assert len(set(nonces)) == 2 and all(len(n) == 32 for n in nonces) and c.verified

def test_client_refuses_an_answer_without_a_valid_proof(fake_server):
    c = ServerClient(fake_server.url, "tok", KEY)
    c.post("/api/agent/heartbeat", {})
    for key in (None, "22" * 32):
        fake_server.server_key = key
        for call in (lambda: c.post("/api/agent/hello", {}), lambda: c.next(0)):
            with pytest.raises(ServerUnverified):
                call()
            assert not c.verified
    fake_server.status_for["/api/agent/next"] = 404  # an unproven 4xx: not our service either
    with pytest.raises(ServerUnverified):
        c.next(0)
    assert issubclass(ServerUnverified, AgentRejected)

def test_client_401_403_and_5xx_need_no_proof(fake_server):
    c = ServerClient(fake_server.url, "tok", KEY)
    fake_server.server_key = None
    fake_server.status_for["/api/agent/heartbeat"] = 401
    with pytest.raises(AgentRejected) as e:
        c.post("/api/agent/heartbeat", {})
    assert not isinstance(e.value, ServerUnverified)
    fake_server.status_for["/api/agent/heartbeat"] = 503
    with pytest.raises(ServerUnavailable):
        c.post("/api/agent/heartbeat", {})

def test_sensitive_posts_wait_for_a_proven_answer_after_an_outage(fake_server):
    """Window titles are only sent once the server proved itself since the last outage (I1)."""
    c = ServerClient(fake_server.url, "tok", KEY)
    with pytest.raises(ServerUnavailable):
        c.post("/api/agent/events", {"events": []}, verified_only=True)
    assert fake_server.requests == []
    c.next(0)
    assert c.post("/api/agent/events", {"events": []}, verified_only=True) is None
    fake_server.status_for["/api/agent/next"] = 503
    with pytest.raises(ServerUnavailable):
        c.next(0)
    with pytest.raises(ServerUnavailable):
        c.post("/api/agent/events", {"events": []}, verified_only=True)
    assert [r[1] for r in fake_server.requests].count("/api/agent/events") == 1

def test_an_unproven_401_after_a_proven_answer_drops_the_trust(fake_server):
    """R2: a 401/403 carries no proof, so it may come from a squatter: nothing sensitive goes out after it."""
    c = ServerClient(fake_server.url, "tok", KEY)
    c.next(0)
    assert c.verified
    fake_server.server_key = None
    for status in (401, 403):
        fake_server.status_for["/api/agent/heartbeat"] = status
        with pytest.raises(AgentRejected):
            c.post("/api/agent/heartbeat", {})
        assert not c.verified
        with pytest.raises(ServerUnavailable):
            c.post("/api/agent/events", {"events": []}, verified_only=True)
        fake_server.server_key = KEY; c.next(0); fake_server.server_key = None
    assert not any(r[1] == "/api/agent/events" for r in fake_server.requests)
