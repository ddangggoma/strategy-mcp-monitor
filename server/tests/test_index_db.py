import sqlite3

import pytest

from app.logstore.fts import InvalidQuery, fts_expression
from app.logstore.index_db import INDEX_SCHEMA_VERSION, open_reader, prepare_index
from app.paths import AppPaths


def test_prepare_index_recreates_on_version_mismatch(tmp_path):
    p = tmp_path / "index.db"
    conn, rebuilt = prepare_index(p); assert rebuilt
    conn.execute("INSERT INTO meta (key, value) VALUES ('x', '1')")
    conn.execute(f"PRAGMA user_version = {INDEX_SCHEMA_VERSION + 1}"); conn.close()
    conn2, rebuilt2 = prepare_index(p)
    assert rebuilt2 and conn2.execute("SELECT COUNT(*) FROM meta").fetchone()[0] == 0
    conn2.close()
    conn3, rebuilt3 = prepare_index(p); assert not rebuilt3; conn3.close()


def test_reader_is_read_only(tmp_path):
    p = tmp_path / "index.db"; prepare_index(p)[0].close()
    r = open_reader(p)
    with pytest.raises(sqlite3.OperationalError):
        r.execute("INSERT INTO meta (key, value) VALUES ('x', '1')")
    r.close()


def test_fts_matches_prefixes_korean_particles_and_hyphenated_commands(tmp_path):
    conn, _ = prepare_index(tmp_path / "index.db")
    conn.execute("INSERT INTO events_fts (rowid, search) VALUES (1, ?)", ("Get-Process | Stop-Process -Name notepad 로그를 메모장",))

    def hit(q):
        return conn.execute("SELECT rowid FROM events_fts WHERE events_fts MATCH ?", (fts_expression(q),)).fetchall()

    for q in ("Stop-Process", "notep", "로그", "메모장 notepad", 'get"process'):
        assert hit(q) == [(1,)], q
    assert hit("otepad") == [] and hit("notepad zebra") == []
    conn.close()


def test_fts_expression_rules():
    assert fts_expression('a "b"') == '"a"* """b"""*'
    assert fts_expression("| --  ") is None and fts_expression(None) is None
    with pytest.raises(InvalidQuery):
        fts_expression(" ".join(f"w{i}" for i in range(11)))
    with pytest.raises(InvalidQuery):
        fts_expression("x" * 101)


# ---- beyond the plan's list ----

def test_index_db_path_is_in_the_data_dir(tmp_path):
    assert AppPaths(tmp_path).index_db_path == tmp_path / "data" / "index.db"


def test_prepare_index_settings_and_schema(tmp_path):
    p = tmp_path / "index.db"
    conn, rebuilt = prepare_index(p)
    assert rebuilt and isinstance(conn, sqlite3.Connection) and conn.isolation_level is None
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert conn.execute("PRAGMA user_version").fetchone()[0] == INDEX_SCHEMA_VERSION
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}
    assert {"meta", "files", "events", "events_fts", "counts_min", "counts_hour", "ux_events_line", "ix_events_ts",
            "ix_events_user", "ix_events_cat", "ix_events_session", "ix_events_ip"} <= names
    # duplicate lines of one day are rejected by the unique key; the same line on another day is not
    ins = "INSERT INTO events (ts_ms, day, cat, line_hash, raw) VALUES (1, ?, 'system', x'0102030405060708', '{}')"
    conn.execute(ins, ("2026-11-04",))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins, ("2026-11-04",))
    conn.execute(ins, ("2026-11-05",))
    # user is case-insensitive in the events table and the rollups
    conn.execute("UPDATE events SET user = 'CORP\\Hong'")
    assert conn.execute("SELECT COUNT(*) FROM events WHERE user = 'corp\\hong'").fetchone()[0] == 2
    conn.execute("INSERT INTO counts_min (bucket, cat, user, n) VALUES (1, 'system', 'Hong', 1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO counts_min (bucket, cat, user, n) VALUES (1, 'system', 'hong', 1)")
    # the contentless FTS table accepts deletes (contentless_delete=1)
    conn.execute("INSERT INTO events_fts (rowid, search) VALUES (5, 'alpha')")
    conn.execute("DELETE FROM events_fts WHERE rowid = 5")
    assert conn.execute("SELECT COUNT(*) FROM events_fts WHERE events_fts MATCH 'alpha'").fetchone()[0] == 0
    conn.close()


@pytest.mark.parametrize("found", [INDEX_SCHEMA_VERSION - 2, INDEX_SCHEMA_VERSION + 7])  # older and newer
def test_prepare_index_wipes_other_versions_with_their_wal_files(tmp_path, found):
    p = tmp_path / "index.db"
    old = sqlite3.connect(p)
    old.execute("CREATE TABLE meta (k)")  # an incompatible older/newer layout
    old.execute(f"PRAGMA user_version = {found}"); old.commit(); old.close()
    (tmp_path / "index.db-wal").write_bytes(b"stale")
    (tmp_path / "index.db-shm").write_bytes(b"stale")
    conn, rebuilt = prepare_index(p)
    assert rebuilt and conn.execute("PRAGMA user_version").fetchone()[0] == INDEX_SCHEMA_VERSION
    assert [r[1] for r in conn.execute("PRAGMA table_info(meta)")] == ["key", "value"]
    conn.close()


def test_prepare_index_replaces_a_file_that_is_not_a_database_or_has_foreign_tables(tmp_path):
    garbage = tmp_path / "garbage.db"; garbage.write_bytes(b"this is not sqlite" * 100)
    foreign = tmp_path / "foreign.db"
    c = sqlite3.connect(foreign); c.execute("CREATE TABLE events (x)"); c.commit(); c.close()  # user_version 0
    for p in (garbage, foreign):
        conn, rebuilt = prepare_index(p)
        assert rebuilt and conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert "ts_ms" in [r[1] for r in conn.execute("PRAGMA table_info(events)")]
        conn.close()


def test_reader_sees_committed_rows_and_returns_named_rows(tmp_path):
    p = tmp_path / "index.db"
    w, _ = prepare_index(p)
    r = open_reader(p)
    w.execute("INSERT INTO meta (key, value) VALUES ('rows', '3')")
    got = r.execute("SELECT key, value FROM meta").fetchone()
    assert (got["key"], got["value"]) == ("rows", "3")
    assert r.execute("PRAGMA query_only").fetchone()[0] == 1
    assert r.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    r.close(); w.close()


def test_fts_expression_drops_punctuation_only_words_and_keeps_unicode():
    assert fts_expression("  로그를  -  Stop-Process ") == '"로그를"* "Stop-Process"*'
    assert fts_expression("   ") is None and fts_expression("") is None
    assert fts_expression(" ".join(f"w{i}" for i in range(10)) + " -- |") is not None  # 10 words + punctuation
    assert fts_expression("x" * 100) == '"' + "x" * 100 + '"*'
