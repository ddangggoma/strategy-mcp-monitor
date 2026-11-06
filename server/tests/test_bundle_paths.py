import json
import sys
from pathlib import Path

from app.__main__ import parse_args, reindex
from app.activity.agent_supervisor import AgentOptions, agent_argv, agent_env
from app.bundle import Bundle, agent_command, default_root, default_static_dir, find_bundle
from app.collect.cli import collector_config

REPO = Path(__file__).resolve().parents[2]


def make_bundle(root: Path, layout: str) -> None:
    (root / "bundle.json").write_text(json.dumps({"layout": layout, "version": "1.0.0", "python": "3.15.2"}), "utf-8")


def test_runtime_layout(tmp_path):
    make_bundle(tmp_path, "runtime")
    exe = tmp_path / "runtime" / "python.exe"; exe.parent.mkdir(); exe.write_bytes(b"")
    b = find_bundle(exe)
    assert b == Bundle(tmp_path, "runtime", "1.0.0")
    assert agent_command(b) == (str(tmp_path / "runtime" / "python.exe"), "-m", "mcp_agent")
    assert default_static_dir(b) == tmp_path / "web"


def test_pyinstaller_layout(tmp_path):
    make_bundle(tmp_path, "pyinstaller")
    exe = tmp_path / "bin" / "monitor" / "mcp-monitor.exe"; exe.parent.mkdir(parents=True); exe.write_bytes(b"")
    assert agent_command(find_bundle(exe)) == (str(tmp_path / "bin" / "agent" / "mcp-agent.exe"),)


def test_no_or_invalid_bundle(tmp_path):
    assert find_bundle(Path(sys.executable)) is None
    (tmp_path / "bundle.json").write_text('{"layout": "zip"}', "utf-8")
    exe = tmp_path / "x.exe"; exe.write_bytes(b"")
    assert find_bundle(exe) is None


def test_default_root(monkeypatch, tmp_path):
    monkeypatch.setenv("ProgramData", str(tmp_path))
    assert default_root(Bundle(tmp_path, "runtime", "1.0.0")) == tmp_path / "MCP Monitor"
    assert default_root(None) == Path.cwd()


def test_agent_argv_and_env_use_the_bundle_command(tmp_path):
    """Plan test; ``agent_env`` also takes the server key (Plan 4 fix wave I1: every launch passes
    ``MCPMON_AGENT_TOKEN`` and ``MCPMON_AGENT_SERVER_KEY``)."""
    o = AgentOptions(command=("C:/MCP/bin/agent/mcp-agent.exe",), dialog="edge")
    assert agent_argv(o, "http://127.0.0.1:8700", 2) == ["C:/MCP/bin/agent/mcp-agent.exe", "--server", "http://127.0.0.1:8700", "--dialog", "edge"]
    assert agent_env(o, "tok", "key") == {"MCPMON_AGENT_TOKEN": "tok", "MCPMON_AGENT_SERVER_KEY": "key"}
    dev = AgentOptions(agent_dir=tmp_path, python="py.exe", dialog="print", url_dir=tmp_path)
    assert agent_argv(dev, "http://127.0.0.1:8700", 3)[:3] == ["py.exe", "-m", "mcp_agent"]
    assert agent_argv(dev, "http://127.0.0.1:8700", 3)[-2:] == ["--url-file", str(tmp_path / "agent-3.url")]
    assert agent_env(dev, "tok", "key") == {"MCPMON_AGENT_TOKEN": "tok", "MCPMON_AGENT_SERVER_KEY": "key", "PYTHONPATH": str(tmp_path)}


# --- beyond the plan's tests ---------------------------------------------------------------

def test_search_stops_three_levels_up(tmp_path):
    make_bundle(tmp_path, "runtime")
    deep = tmp_path / "a" / "b" / "c" / "x.exe"; deep.parent.mkdir(parents=True); deep.write_bytes(b"")
    assert find_bundle(deep) is None  # c, b, a: the root is the 4th level
    near = tmp_path / "a" / "b" / "x.exe"; near.write_bytes(b"")
    assert find_bundle(near) == Bundle(tmp_path, "runtime", "1.0.0")


def test_nearest_bundle_json_wins_and_an_invalid_one_is_not_skipped(tmp_path):
    make_bundle(tmp_path, "runtime")
    inner = tmp_path / "inner"; inner.mkdir()
    (inner / "bundle.json").write_text(json.dumps({"layout": "pyinstaller", "version": "2.0.0"}), "utf-8")
    exe = inner / "bin" / "x.exe"; exe.parent.mkdir(); exe.write_bytes(b"")
    assert find_bundle(exe) == Bundle(inner, "pyinstaller", "2.0.0")
    (inner / "bundle.json").write_text("not json", "utf-8")
    assert find_bundle(exe) is None  # never falls through to an outer folder's bundle.json


def test_bundle_json_shapes_that_are_ignored(tmp_path):
    exe = tmp_path / "x.exe"; exe.write_bytes(b"")
    for text in ('["runtime"]', '{"layout": "runtime"}', '{"layout": "runtime", "version": 1}',
                 '{"layout": "runtime", "version": ""}', '{"version": "1.0.0"}', "\xff\xfe"):
        (tmp_path / "bundle.json").write_text(text, "utf-8")
        assert find_bundle(exe) is None, text
    (tmp_path / "bundle.json").unlink(); (tmp_path / "bundle.json").mkdir()
    assert find_bundle(exe) is None


def test_development_defaults_without_a_bundle(tmp_path):
    assert default_static_dir(None) == REPO / "web" / "dist"
    assert agent_command(None, "py.exe") == ("py.exe", "-m", "mcp_agent")
    assert agent_command(None) == (sys.executable, "-m", "mcp_agent")


def test_cli_defaults_come_from_the_bundle(monkeypatch, tmp_path, clock):
    make_bundle(tmp_path, "runtime")
    exe = tmp_path / "runtime" / "python.exe"; exe.parent.mkdir(); exe.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setenv("ProgramData", str(tmp_path / "pd"))
    ns = parse_args(["--session-source", f"json:{tmp_path / 's.json'}", "--agent-launcher", "local"])
    assert (ns.root, ns.static_dir, ns.agent_dir) == (tmp_path / "pd" / "MCP Monitor", tmp_path / "web", tmp_path)
    cfg = collector_config(ns, clock=clock, root=ns.root)
    assert cfg.agent.command == (str(exe), "-m", "mcp_agent") and cfg.agent.agent_dir == tmp_path
    argv = agent_argv(cfg.agent, "http://127.0.0.1:8700", 2)
    assert argv[:3] == [str(exe), "-m", "mcp_agent"] and "PYTHONPATH" not in agent_env(cfg.agent, "t", "k")
    explicit = parse_args(["--root", str(tmp_path / "r"), "--static-dir", "w", "--agent-dir", str(tmp_path / "ag")])
    assert (explicit.root, explicit.static_dir, explicit.agent_dir) == (tmp_path / "r", Path("w"), tmp_path / "ag")


def test_cli_development_defaults_keep_the_base_interpreter(tmp_path, clock):
    ns = parse_args([])
    assert (ns.root, ns.static_dir, ns.agent_dir) == (Path.cwd(), REPO / "web" / "dist", REPO / "agent")
    cfg = collector_config(parse_args(["--session-source", "none"]), clock=clock, root=tmp_path)
    assert cfg.agent.command is None and cfg.agent.agent_dir == REPO / "agent"
    assert agent_env(cfg.agent, "t", "k")["PYTHONPATH"] == str(REPO / "agent")


def test_reindex_defaults_to_the_bundle_root(monkeypatch, tmp_path, capsys):
    make_bundle(tmp_path, "pyinstaller")
    exe = tmp_path / "bin" / "monitor" / "mcp-monitor.exe"; exe.parent.mkdir(parents=True); exe.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setenv("ProgramData", str(tmp_path / "pd"))
    assert reindex([]) == 0
    assert (tmp_path / "pd" / "MCP Monitor" / "data").is_dir()
    assert "indexed 0 rows from 0 files" in capsys.readouterr().out
