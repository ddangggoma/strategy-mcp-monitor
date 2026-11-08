import json
import sqlite3
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.monitor.models import (
    ALERT_ONLY_ISSUES,
    CheckResult,
    Issue,
    Mcp,
    McpConfig,
    McpState,
)
from app.monitor.store import EndpointTakenError, McpNotFoundError, McpStore, NameTakenError
from app.users.store import UserStore
from tests.mcp_helpers import cfg


@pytest.fixture
def env(db, clock):
    users = UserStore(db, clock)
    owner = users.create("o@x.com", "o", "developer", None)
    users.create("a@x.com", "a", "admin", None)
    return McpStore(db, clock, users), users, owner


def test_enums():
    assert [s.value for s in McpState] == [s.name for s in McpState]
    assert [i.value for i in Issue] == [i.name for i in Issue]
    assert ALERT_ONLY_ISSUES == frozenset({Issue.NETWORK_DOWN, Issue.WRONG_PROCESS})
    c = CheckResult(datetime(2026, 1, 1, tzinfo=UTC), None, None, None, None, None)
    assert c.issue is None


def test_defaults():
    c = cfg()
    assert (c.path, c.probe, c.action_delay_sec, c.startup_grace_sec, c.max_auto_actions, c.window_sec) == (
        "/mcp", "mcp_ping", 30, 30, 3, 600)
    assert (c.auto_recovery, c.autostart_on_boot, c.maintenance, c.script_timeout_sec, c.expected_process_name) == (
        True, False, False, 120, None)
    assert c.icon is None


def test_a_row_stored_before_icons_existed_stays_valid_and_takes_an_icon(env, db):
    store, _users, owner = env
    mcp = store.create(cfg(), owner.id)
    legacy = {k: v for k, v in json.loads(cfg().model_dump_json()).items() if k != "icon"}
    with db.transaction() as conn:
        conn.execute("UPDATE mcps SET config = ? WHERE id = ?", (json.dumps(legacy), mcp.id))
    old = store.get(mcp.id)
    assert old.config_error is None and old.config.icon is None
    _before, after = store.update(mcp.id, {"icon": "☀️"})
    assert after.config.icon == "☀️"
    assert json.loads(db.query("SELECT config FROM mcps WHERE id = ?", (mcp.id,))[0]["config"])["icon"] == "☀️"


@pytest.mark.parametrize("bad", [
    {"port": 0}, {"port": 65536}, {"host": "-x"}, {"host": "a b"}, {"host": ""}, {"name": " "}, {"name": "x" * 65},
    {"path": "mcp"}, {"script_timeout_sec": 9}, {"script_timeout_sec": 121}, {"action_delay_sec": 0},
    {"probe": "http"}, {"bogus": 1}, {"auto_recovery": "yes"},
    # types are strict: no coercion from strings/floats/bools
    {"port": "9102"}, {"port": 9102.0}, {"port": True}, {"name": 5}, {"host": 5}, {"host": None},
    # path
    {"path": "/a b"}, {"path": "/" + "x" * 200}, {"path": ""},
    # host forms that are not hostnames or IP literals
    {"host": "a..b"}, {"host": "a-"}, {"host": "a_b"}, {"host": "x" * 64 + ".com"}, {"host": ("a" * 63 + ".") * 4 + "com"},
    {"host": "999.1.1.1"}, {"host": "1.2.3"}, {"host": "fe80::1%eth0"}, {"host": "[::1]"}, {"host": "a.b:80"},
    {"host": "http://x"}, {"host": "ホスト"},
    # numeric bounds
    {"expected_process_name": ""}, {"expected_process_name": "x" * 261}, {"expected_process_name": 1},
    {"action_delay_sec": 3601}, {"startup_grace_sec": -1}, {"startup_grace_sec": 601},
    {"max_auto_actions": 0}, {"max_auto_actions": 21}, {"window_sec": 59}, {"window_sec": 86401},
    {"autostart_on_boot": 1}, {"maintenance": "false"}, {"name": None},
    # icon: exactly one emoji, never markup, URLs or names (more cases: test_icon_emoji.py)
    {"icon": "skull"}, {"icon": ""}, {"icon": "<svg/>"}, {"icon": "data:image/png;base64,AA"}, {"icon": 3},
    {"icon_color": "blue"},
])
def test_config_rejects(bad):
    with pytest.raises(ValidationError):
        cfg(**bad)


@pytest.mark.parametrize("ok", [
    {"port": 1}, {"port": 65535}, {"name": "x" * 64}, {"name": "  padded  "}, {"path": "/"}, {"path": "/" + "x" * 199},
    {"expected_process_name": "x"}, {"expected_process_name": "x" * 260},
    {"action_delay_sec": 1}, {"action_delay_sec": 3600}, {"startup_grace_sec": 0}, {"startup_grace_sec": 600},
    {"max_auto_actions": 1}, {"max_auto_actions": 20}, {"window_sec": 60}, {"window_sec": 86400},
    {"script_timeout_sec": 10}, {"script_timeout_sec": 120},
    {"probe": "tcp"}, {"probe": "icmp"}, {"host": "a"}, {"host": "my-host.example.com"}, {"host": "a1.2b"},
    {"host": "x" * 63 + ".com"},
    {"icon": "🤖"}, {"icon": "🇰🇷"}, {"icon": None},
])
def test_config_accepts_boundaries(ok):
    assert cfg(**ok)


def test_name_is_stripped():
    assert cfg(name="  padded  ").name == "padded"


def test_host_normalized():
    assert cfg(host=" LocalHost ").host == "localhost"
    assert cfg(host="::1").host == "::1"
    assert cfg(host=" 10.0.0.1 ").host == "10.0.0.1"
    assert cfg(host="FE80:0000:0000:0000:0000:0000:0000:ABCD").host == "fe80::abcd"
    assert cfg(host="0:0:0:0:0:0:0:1").host == "::1"


def _mcp(host, port=9102, path="/mcp"):
    return Mcp(1, cfg(host=host, port=port, path=path), None, None, datetime(2026, 1, 1, tzinfo=UTC))


def test_mcp_url():
    assert _mcp("127.0.0.1").url == "http://127.0.0.1:9102/mcp"
    assert _mcp("localhost", 80, "/a/b").url == "http://localhost:80/a/b"
    assert _mcp("::1").url == "http://[::1]:9102/mcp"
    assert _mcp("fe80::abcd", 1, "/").url == "http://[fe80::abcd]:1/"


def test_create_get_list(env):
    s, _, owner = env
    m = s.create(cfg(), owner.id)
    assert s.get(m.id).config == cfg() and s.get(m.id).owner_id == owner.id
    assert m.url == "http://127.0.0.1:9102/mcp" and [x.id for x in s.list()] == [m.id]


def test_create_records_creator_and_time(env, clock):
    s, _, owner = env
    m = s.create(cfg(), owner.id)
    assert m.created_by == owner.id and m.created_at == clock.now()
    assert s.get(999) is None


def test_list_ordered_by_name_case_insensitive(env):
    s, _, owner = env
    for i, name in enumerate(["beta", "Alpha", "gamma", "Delta"]):
        s.create(cfg(name=name, port=9200 + i), owner.id)
    assert [m.config.name for m in s.list()] == ["Alpha", "beta", "Delta", "gamma"]


def test_config_persists_all_fields(env):
    s, _, owner = env
    c = cfg(path="/x", probe="tcp", expected_process_name="python.exe", action_delay_sec=7, startup_grace_sec=0,
            max_auto_actions=2, window_sec=60, auto_recovery=False, autostart_on_boot=True, maintenance=True,
            script_timeout_sec=10, host="::1")
    m = s.create(c, owner.id)
    assert s.get(m.id).config == c


def test_unique_name_and_endpoint(env):
    s, _, owner = env
    s.create(cfg(), owner.id)
    with pytest.raises(NameTakenError):
        s.create(cfg(name="CALC", port=9200), owner.id)
    with pytest.raises(EndpointTakenError):
        s.create(cfg(name="other"), owner.id)


def test_endpoint_uniqueness_is_host_and_port(env):
    s, _, owner = env
    s.create(cfg(), owner.id)
    s.create(cfg(name="other-port", port=9103), owner.id)
    s.create(cfg(name="other-host", host="127.0.0.2"), owner.id)
    s.create(cfg(name="v6", host="::1"), owner.id)
    with pytest.raises(EndpointTakenError):  # same endpoint through a differently written host
        s.create(cfg(name="v6-again", host="0:0:0:0:0:0:0:1"), owner.id)
    with pytest.raises(EndpointTakenError):
        s.create(cfg(name="shouty", host="127.0.0.1"), owner.id)
    assert len(s.list()) == 4


def test_failed_create_leaves_no_row_and_store_stays_usable(env):
    s, _, owner = env
    s.create(cfg(), owner.id)
    for kw in ({"name": "calc", "port": 1}, {"name": "x"}):
        with pytest.raises((NameTakenError, EndpointTakenError)):
            s.create(cfg(**kw), owner.id)
    assert len(s.list()) == 1
    assert s.create(cfg(name="fine", port=9300), owner.id).config.name == "fine"


def test_unknown_owner_is_not_mapped_to_a_conflict(env):
    s, _, _ = env
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        s.create(cfg(), 9999)
    assert s.list() == []


def test_insert_joins_callers_transaction(env, db):
    s, _, owner = env
    with pytest.raises(RuntimeError), db.transaction() as conn:
        s.insert(conn, cfg(), owner.id, owner.id)
        raise RuntimeError
    assert s.list() == []
    with db.transaction() as conn:
        mcp_id = s.insert(conn, cfg(), owner.id, owner.id)
        with pytest.raises(NameTakenError):
            s.insert(conn, cfg(port=9200), owner.id, owner.id)
    assert [m.id for m in s.list()] == [mcp_id]


def test_update(env):
    s, _, owner = env
    m = s.create(cfg(), owner.id)
    before, after = s.update(m.id, {"action_delay_sec": 5})
    assert before.config.action_delay_sec == 30 and after.config.action_delay_sec == 5
    for bad in ({"port": 0}, {"bogus": 1}):
        with pytest.raises(ValidationError):
            s.update(m.id, bad)
    assert s.get(m.id).config.port == 9102
    with pytest.raises(McpNotFoundError):
        s.update(999, {"port": 1})


def test_update_keeps_columns_in_sync_with_config(env, db):
    s, _, owner = env
    m = s.create(cfg(), owner.id)
    s.update(m.id, {"name": "  Renamed ", "host": "LOCALHOST", "port": 9500})
    row = db.query("SELECT name, host, port, config FROM mcps WHERE id = ?", (m.id,))[0]
    assert (row["name"], row["host"], row["port"]) == ("Renamed", "localhost", 9500)
    assert McpConfig.model_validate_json(row["config"]) == s.get(m.id).config
    assert s.get(m.id).config.name == "Renamed"


def test_update_does_not_touch_identity_fields(env):
    s, _, owner = env
    m = s.create(cfg(), owner.id)
    _, after = s.update(m.id, {"maintenance": True})
    assert (after.id, after.owner_id, after.created_by, after.created_at) == (
        m.id, m.owner_id, m.created_by, m.created_at)


def test_update_can_clear_optional_field(env):
    s, _, owner = env
    m = s.create(cfg(expected_process_name="python.exe"), owner.id)
    assert s.update(m.id, {"expected_process_name": None})[1].config.expected_process_name is None


def test_update_empty_patch_is_a_noop(env):
    s, _, owner = env
    m = s.create(cfg(), owner.id)
    before, after = s.update(m.id, {})
    assert before == after == m


def test_update_conflicts_map_to_domain_errors(env):
    s, _, owner = env
    a = s.create(cfg(), owner.id)
    b = s.create(cfg(name="b", port=9200), owner.id)
    with pytest.raises(NameTakenError):
        s.update(b.id, {"name": "CALC"})
    with pytest.raises(EndpointTakenError):
        s.update(b.id, {"port": 9102})
    with pytest.raises(EndpointTakenError):
        s.update(b.id, {"host": "127.0.0.1", "port": 9102})
    assert s.get(b.id) == b  # the failed updates left no trace
    assert s.update(a.id, {"name": "CALC"})[1].config.name == "CALC"  # own name, other case: allowed
    assert s.update(b.id, {"port": 9201})[1].config.port == 9201  # the store works after a failure


def test_update_validation_error_leaves_row_and_store_usable(env):
    s, _, owner = env
    m = s.create(cfg(), owner.id)
    with pytest.raises(ValidationError):
        s.update(m.id, {"port": "9500"})
    assert s.get(m.id) == m
    assert s.update(m.id, {"port": 9500})[1].config.port == 9500


def test_effective_owner(env, db, clock):
    s, users, owner = env
    m = s.create(cfg(), owner.id)
    assert s.effective_owner_id(m) == owner.id
    users.set_active(owner.id, False)
    assert s.effective_owner_id(s.get(m.id)) is None


def test_effective_owner_without_owner(env, db):
    s, _, owner = env
    m = s.create(cfg(), owner.id)
    db.execute("UPDATE mcps SET owner_id = NULL WHERE id = ?", (m.id,))
    assert s.get(m.id).owner_id is None
    assert s.effective_owner_id(s.get(m.id)) is None


def test_maintenance_owner_delete_cascade(env, db):
    s, users, owner = env
    m = s.create(cfg(), owner.id)
    assert s.set_maintenance(m.id, True).config.maintenance is True
    other = users.create("b@x.com", "b", "developer", None)
    assert s.set_owner(m.id, other.id).owner_id == other.id
    db.execute("INSERT INTO mcp_minutes(mcp_id, minute, ok, total) VALUES (?, '2026-11-04T05:00Z', 1, 1)", (m.id,))
    s.delete(m.id)
    assert s.get(m.id) is None and db.query("SELECT * FROM mcp_minutes") == []
    with pytest.raises(McpNotFoundError):
        s.delete(m.id)


def test_maintenance_toggle_off_and_not_found(env):
    s, _, owner = env
    m = s.create(cfg(), owner.id)
    s.set_maintenance(m.id, True)
    assert s.set_maintenance(m.id, False).config.maintenance is False
    with pytest.raises(McpNotFoundError):
        s.set_maintenance(999, True)
    with pytest.raises(McpNotFoundError):
        s.set_owner(999, owner.id)


def test_set_owner_to_unknown_user_is_rejected(env):
    s, _, owner = env
    m = s.create(cfg(), owner.id)
    with pytest.raises(sqlite3.IntegrityError):
        s.set_owner(m.id, 9999)
    assert s.get(m.id).owner_id == owner.id


def test_delete_cascades_every_child_table(env, db):
    s, _, owner = env
    m = s.create(cfg(), owner.id)
    keep = s.create(cfg(name="keep", port=9200), owner.id)
    for mid in (m.id, keep.id):
        db.execute("INSERT INTO mcp_scripts(mcp_id, kind, ext, sha256, version, updated_at) VALUES (?, 'start', '.ps1', 'h', 1, 't')", (mid,))
        db.execute("INSERT INTO mcp_script_versions(mcp_id, kind, version, created_at) VALUES (?, 'start', 1, 't')", (mid,))
        db.execute("INSERT INTO mcp_minutes(mcp_id, minute, ok, total) VALUES (?, 'm', 1, 1)", (mid,))
        db.execute("INSERT INTO mcp_transitions(mcp_id, at, from_state, to_state) VALUES (?, 't', 'HEALTHY', 'SUSPECT')", (mid,))
        db.execute(
            "INSERT INTO mcp_actions(run_id, mcp_id, at, requested, kind, trigger, reason, status, duration_ms)"
            " VALUES ('r', ?, 't', 'restart', 'restart', 'auto', 'PROCESS_DOWN', 'ok', 1)", (mid,))
    s.delete(m.id)
    for table in ("mcp_scripts", "mcp_script_versions", "mcp_minutes", "mcp_transitions", "mcp_actions"):
        assert [r["mcp_id"] for r in db.query(f"SELECT mcp_id FROM {table}")] == [keep.id], table


def test_ids_not_reused(env):
    s, _, owner = env
    a = s.create(cfg(), owner.id)
    s.delete(a.id)
    assert s.create(cfg(), owner.id).id > a.id


def test_ids_not_reused_after_deleting_the_newest(env):
    s, _, owner = env
    s.create(cfg(), owner.id)
    last = s.create(cfg(name="last", port=9200), owner.id)
    s.delete(last.id)  # rowid-only tables would hand out last.id again
    assert s.create(cfg(name="next", port=9300), owner.id).id == last.id + 1


def test_scripts_table_constraints(db, env):
    s, _, owner = env
    m = s.create(cfg(), owner.id)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO mcp_scripts(mcp_id, kind, ext, sha256, version, updated_at) VALUES (?, 'bogus', '.ps1', 'h', 1, 't')", (m.id,))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO mcp_scripts(mcp_id, kind, ext, sha256, version, updated_at) VALUES (?, 'start', '.sh', 'h', 1, 't')", (m.id,))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO mcp_scripts(mcp_id, kind, ext, sha256, version, updated_at) VALUES (999, 'start', '.ps1', 'h', 1, 't')")


# ---- I1: name allowlist (MCP_NAME reaches cmd as %MCP_NAME%, expanded before parsing) ----

NAME_FORBIDDEN = [*map(chr, range(0x00, 0x20)), "\x7f", *map(chr, range(0x80, 0xA0)),
                  "%", "^", "&", "|", "<", ">", '"', "!", "`",
                  # parentheses close/open a cmd block; the rest are cmd/PowerShell separators or specials
                  "(", ")", ",", ";", "=", "'", "@", "$", "#", "*", "?", "[", "]", "{", "}", "~", "/", "\\",
                  ":", "+", " ", "　", " ", "​", "﻿", "☃", "\U0001f600"]


@pytest.mark.parametrize("ch", NAME_FORBIDDEN, ids=lambda c: f"U+{ord(c):04X}")
def test_name_rejects_shell_and_control_characters(ch):
    with pytest.raises(ValidationError):
        cfg(name=f"calc{ch}x")
    stored = json.dumps({"name": f"calc{ch}x", "host": "127.0.0.1", "port": 9102})
    with pytest.raises(ValidationError):  # the path stored rows take
        McpConfig.model_validate_json(stored)


@pytest.mark.parametrize("ch", [*map(chr, range(0x00, 0x20)), "\x7f", *map(chr, range(0x80, 0xA0))],
                         ids=lambda c: f"U+{ord(c):04X}")
def test_expected_process_name_rejects_control_characters(ch):
    with pytest.raises(ValidationError):
        cfg(expected_process_name=f"python{ch}.exe")


@pytest.mark.parametrize("name", [
    "calc (v2)", "a ) else ( echo X", "a)b", "a(b", "a,b", "a;b", "a=b", "a'b", "a@b", "a\tb",
])
def test_name_rejects_non_allowlisted_text(name):
    with pytest.raises(ValidationError):
        cfg(name=name)


@pytest.mark.parametrize("name", ["서울 날씨", "calc-v2.1_test", "my_mcp-1.0", "a.b", "Ünïcödé", "x" * 64, "날씨 2"])
def test_name_accepts_plain_text(name):
    assert cfg(name=name).name == name


def test_injected_name_cannot_be_stored(env):
    store, _, owner = env
    m = store.create(cfg(), owner.id)
    with pytest.raises(ValidationError):
        store.create(cfg(name="calc & echo X", port=9200), owner.id)
    with pytest.raises(ValidationError):
        store.update(m.id, {"name": "calc & echo X"})
    for bad in ("a ) else ( echo X", "a)b"):
        with pytest.raises(ValidationError):
            store.create(cfg(name=bad, port=9201), owner.id)
        with pytest.raises(ValidationError):
            store.update(m.id, {"name": bad})
    assert [x.config.name for x in store.list()] == ["calc"]
