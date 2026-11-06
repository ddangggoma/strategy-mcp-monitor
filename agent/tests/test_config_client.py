import socket
from pathlib import Path

import pytest

from mcp_agent.client import AgentRejected, ServerClient, ServerUnavailable
from mcp_agent.config import parse_args


def test_config_requires_token_and_server():
    with pytest.raises(SystemExit) as e:
        parse_args(["--server", "http://127.0.0.1:8700"], {})
    assert e.value.code == 2
    with pytest.raises(SystemExit):
        parse_args([], {"MCPMON_AGENT_TOKEN": "t"})

def test_config_reads_and_removes_the_token():
    env = {"MCPMON_AGENT_TOKEN": "tok", "OTHER": "1"}
    cfg = parse_args(["--server", "http://127.0.0.1:8700/", "--dialog", "print", "--url-file", "u.url"], env)
    assert (cfg.server, cfg.token, cfg.dialog, cfg.url_file, cfg.unreachable_exit_sec) == ("http://127.0.0.1:8700", "tok", "print", Path("u.url"), 120)
    assert "MCPMON_AGENT_TOKEN" not in env and env["OTHER"] == "1"
    assert parse_args(["--server", "http://x"], {"MCPMON_AGENT_TOKEN": "t"}).dialog == "edge"

def test_client_sends_token_and_json(fake_server):
    c = ServerClient(fake_server.url, "tok")
    assert c.post("/api/agent/hello", {"session_id": 1, "title": "메모"}) == fake_server.hello_body
    method, path, body, headers = fake_server.requests[-1]
    assert (method, path, body, headers["X-Agent-Token"], headers["Content-Type"]) == \
        ("POST", "/api/agent/hello", {"session_id": 1, "title": "메모"}, "tok", "application/json")

def test_client_maps_statuses(fake_server):
    c = ServerClient(fake_server.url, "tok")
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
        ServerClient(f"http://127.0.0.1:{port}", "t", timeout=1).post("/api/agent/hello", {})

def test_agent_never_touches_the_database():
    src = "\n".join(p.read_text("utf-8") for p in (Path(__file__).parents[1] / "mcp_agent").glob("*.py"))
    assert "sqlite3" not in src and "config.db" not in src


# --- beyond the plan ---------------------------------------------------------------------------

def test_config_defaults_and_print_needs_a_url_file():
    cfg = parse_args(["--server", "http://127.0.0.1:8700"], {"MCPMON_AGENT_TOKEN": "t", "LOCALAPPDATA": r"C:\Users\u\AppData\Local"})
    assert (cfg.dialog, cfg.url_file, cfg.edge_path) == ("edge", None, None)
    assert cfg.profile_dir == Path(r"C:\Users\u\AppData\Local") / "mcp-monitor" / "notice-edge"
    assert isinstance(cfg.unreachable_exit_sec, float) and cfg.unreachable_exit_sec == 120.0
    cfg = parse_args(["--server", "http://x", "--edge-path", r"D:\e\msedge.exe", "--profile-dir", r"D:\p",
                      "--unreachable-exit-sec", "7.5"], {"MCPMON_AGENT_TOKEN": "t"})
    assert (cfg.edge_path, cfg.profile_dir, cfg.unreachable_exit_sec) == (r"D:\e\msedge.exe", Path(r"D:\p"), 7.5)
    env = {"MCPMON_AGENT_TOKEN": "t"}
    with pytest.raises(SystemExit) as e:
        parse_args(["--server", "http://x", "--dialog", "print"], env)
    assert e.value.code == 2 and "MCPMON_AGENT_TOKEN" not in env

def test_config_rejects_an_empty_token():
    with pytest.raises(SystemExit) as e:
        parse_args(["--server", "http://x"], {"MCPMON_AGENT_TOKEN": ""})
    assert e.value.code == 2

def test_client_next_long_polls_with_the_timeout_and_returns_the_command(fake_server):
    fake_server.commands.append({"type": "exit"})
    c = ServerClient(fake_server.url, "tok")
    assert c.next(25.0) == {"type": "exit"}
    method, path, body, headers = fake_server.requests[-1]
    assert (method, path, body, headers["X-Agent-Token"]) == ("GET", "/api/agent/next", None, "tok")

def test_client_post_without_a_body(fake_server):
    assert ServerClient(fake_server.url, "tok").post("/api/agent/notice/7/closed") is None
    method, path, body, headers = fake_server.requests[-1]
    assert (method, path, body, headers["X-Agent-Token"]) == ("POST", "/api/agent/notice/7/closed", None, "tok")
    assert "Content-Type" not in headers

def test_client_maps_401_and_other_4xx(fake_server):
    c = ServerClient(fake_server.url, "tok")
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
    assert ServerClient(fake_server.url, "tok").post("/api/agent/heartbeat", {"idle_sec": 1}) is None
    assert fake_server.requests[-1][1] == "/api/agent/heartbeat"

def test_client_read_timeout_is_unavailable():
    with socket.socket() as s:  # accepts the connection (backlog) but never answers
        s.bind(("127.0.0.1", 0)); s.listen(1); port = s.getsockname()[1]
        with pytest.raises(ServerUnavailable):
            ServerClient(f"http://127.0.0.1:{port}", "t", timeout=0.3).post("/api/agent/hello", {})
