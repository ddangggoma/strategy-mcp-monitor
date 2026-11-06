from pathlib import Path

import pytest

from app.__main__ import parse_args
from app.collect.cli import collector_config
from app.main import server_configs
from app.sessions.jsonsource import JsonFileWtsSource
from app.web.app_factory import create_app
from app.win.eventlog import PywinEventLogSource
from app.win.wts import CtypesWtsSource

REPO = Path(__file__).resolve().parents[2]


def test_defaults():
    ns = parse_args([])
    assert ns.static_dir == REPO / "web" / "dist" and ns.dev_otp_code is None
    assert ns.external_host == "0.0.0.0" and ns.allow_lan_dev is False
    assert (ns.local_port, ns.external_port) == (8700, 8701)


def test_static_dir_option():
    assert parse_args(["--static-dir", "somewhere"]).static_dir == Path("somewhere")


def test_dev_otp_code_ok_on_loopback_external_host():
    ns = parse_args(["--dev-otp-code", "246810", "--external-host", "127.0.0.1"])
    assert ns.dev_otp_code == "246810" and ns.external_host == "127.0.0.1"


@pytest.mark.parametrize(
    "bad", ["12345", "1234567", "12a456", "１２３４５６", " 246810", "246810 ", "246810\n", "", "+12345", "١٢٣٤٥٦"]
)
def test_dev_otp_code_must_be_six_ascii_digits(bad):
    with pytest.raises(SystemExit) as e:
        parse_args(["--dev-otp-code", bad, "--external-host", "127.0.0.1"])
    assert e.value.code == 2


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.0.7", "example.test"])
def test_dev_otp_code_refused_on_a_lan_reachable_external_host(host, capsys):
    with pytest.raises(SystemExit) as e:
        parse_args(["--dev-otp-code", "246810", "--external-host", host])
    assert e.value.code == 2
    assert "--allow-lan-dev" in capsys.readouterr().err


def test_dev_otp_code_with_default_external_host_is_refused(capsys):
    with pytest.raises(SystemExit) as e:
        parse_args(["--dev-otp-code", "246810"])
    assert e.value.code == 2
    assert "--allow-lan-dev" in capsys.readouterr().err


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.0.7"])
def test_allow_lan_dev_lifts_the_refusal(host):
    ns = parse_args(["--dev-otp-code", "246810", "--external-host", host, "--allow-lan-dev"])
    assert ns.dev_otp_code == "246810" and ns.external_host == host


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_hosts_need_no_lan_flag(host):
    assert parse_args(["--dev-otp-code", "246810", "--external-host", host]).external_host == host


def test_no_dev_code_means_any_external_host_is_fine():
    assert parse_args(["--external-host", "0.0.0.0"]).dev_otp_code is None


def test_session_source_flags(tmp_path, clock):
    assert isinstance(collector_config(parse_args([]), clock=clock, root=tmp_path).wts, CtypesWtsSource)
    assert collector_config(parse_args(["--session-source", "none"]), clock=clock, root=tmp_path).wts is None
    cfg = collector_config(parse_args(["--session-source", f"json:{tmp_path / 's.json'}", "--collect-console"]), clock=clock, root=tmp_path)
    assert isinstance(cfg.wts, JsonFileWtsSource) and cfg.collect_console is True


def test_session_source_rejects_unknown():
    with pytest.raises(SystemExit) as e:
        parse_args(["--session-source", "bogus"])
    assert e.value.code == 2


@pytest.mark.parametrize("bad", ["json:", "WTS", "json", "none "])
def test_session_source_rejects_malformed(bad, capsys):
    with pytest.raises(SystemExit) as e:
        parse_args(["--session-source", bad])
    assert e.value.code == 2 and "--session-source" in capsys.readouterr().err


def test_session_source_defaults_and_dev_warning(tmp_path, clock, capsys):
    ns = parse_args([])
    assert ns.session_source == "wts" and ns.collect_console is False
    cfg = collector_config(ns, clock=clock, root=tmp_path)
    assert cfg.collect_console is False and cfg.poll_interval_sec == 0.5
    assert "WARNING" not in capsys.readouterr().err
    path = tmp_path / "s.json"
    path.write_text('{"sessions": [{"session_id": 4, "user": "kim"}]}', "utf-8")
    cfg = collector_config(parse_args(["--session-source", f"json:{path}"]), clock=clock, root=tmp_path)
    assert "WARNING: dev session source" in capsys.readouterr().err
    assert [s.session_id for s in cfg.wts.snapshot().sessions] == [4]


def test_server_configs_bind_the_external_host(services):
    local, external = create_app("local", services), create_app("external", services)
    cfgs = server_configs(local, external, 1, 2, external_host="127.0.0.1")
    assert [(c.host, c.port) for c in cfgs] == [("127.0.0.1", 1), ("127.0.0.1", 2)]
    assert server_configs(local, external)[1].host == "0.0.0.0"


def test_event_log_source_follows_the_session_source(tmp_path, clock):
    cfg = collector_config(parse_args([]), clock=clock, root=tmp_path)
    assert isinstance(cfg.event_log, PywinEventLogSource) and cfg.bookmarks_path is None
    assert collector_config(parse_args(["--session-source", "none"]), clock=clock, root=tmp_path).event_log is None
    path = tmp_path / "s.json"; path.write_text('{"sessions": []}', "utf-8")
    assert collector_config(parse_args(["--session-source", f"json:{path}"]), clock=clock, root=tmp_path).event_log is None


def test_activity_flag_controls_process_collection(tmp_path, clock):
    from app.win.wmi import WmiProcessSource
    cfg = collector_config(parse_args([]), clock=clock, root=tmp_path)
    assert isinstance(cfg.process, WmiProcessSource) and cfg.activity is True
    off = collector_config(parse_args(["--activity", "off"]), clock=clock, root=tmp_path)
    assert off.process is None and off.activity is False and isinstance(off.wts, CtypesWtsSource)
    assert collector_config(parse_args(["--session-source", "none"]), clock=clock, root=tmp_path).process is None
    path = tmp_path / "s.json"; path.write_text('{"sessions": []}', "utf-8")
    dev = collector_config(parse_args(["--session-source", f"json:{path}", "--activity", "on"]), clock=clock, root=tmp_path)
    assert dev.process is None and dev.activity is True


def test_activity_flag_rejects_other_values(capsys):
    with pytest.raises(SystemExit) as e:
        parse_args(["--activity", "maybe"])
    assert e.value.code == 2 and "--activity" in capsys.readouterr().err
