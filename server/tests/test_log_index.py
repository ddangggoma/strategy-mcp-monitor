import asyncio
import sqlite3
import threading
import time
from contextlib import closing

import pytest
import pytest_asyncio

from app.__main__ import main
from app.logstore.index_db import INDEX_SCHEMA_VERSION, prepare_index
from app.logstore.indexer import IndexReader, LogIndex
from app.logstore.writer import DailyJsonlWriter, LogWriter
from tests.log_helpers import ev, index_all, write_gz, write_lines
from tests.winfakes import ListLog, eventually


@pytest_asyncio.fixture
async def env(tmp_path, clock):  # clock: 2026-11-04 14:00 KST
    logs = tmp_path / "logs"; logs.mkdir()
    log = ListLog()
    idx = LogIndex(tmp_path / "index.db", logs, clock, log, batch_lines=3, backlog_lines_per_cycle=4)
    await idx.start(run_loop=False)
    yield idx, logs, log
    await idx.stop()


def sys_events(log, name):
    return [f for cat, _at, f in log.events if cat == "system" and f.get("event") == name]


async def test_indexes_complete_lines_and_tails_partial_ones(env):
    idx, logs, _ = env
    a = ev("2026-11-04T14:00:00.000+09:00", "system", event="a")
    b = ev("2026-11-04T14:00:01.000+09:00", "system", event="b")
    (logs / "2026-11-04.jsonl").write_bytes(a + b"\n" + b[:10])
    assert await idx.index_once() == 1
    with (logs / "2026-11-04.jsonl").open("ab") as fh: fh.write(b[10:] + b"\n")
    assert await idx.index_once() == 1 and idx.reader().summary().rows == 2 and idx.status().ready


async def test_duplicate_lines_from_a_retry_are_indexed_once(env):
    idx, logs, _ = env
    a = ev("2026-11-04T14:00:00.000+09:00", "auth", event="login", email="a@x.com", ok=True)
    write_lines(logs, "2026-11-04", [a, a, a])
    assert await idx.index_once() == 1


async def test_recent_days_first_then_backlog_newest_first(env):
    idx, logs, _ = env
    for day in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-11-04"):
        write_lines(logs, day, [ev(f"{day}T10:00:0{i}.000+09:00", "system", i=i) for i in range(3)])
    await idx.index_once()
    assert idx.reader().days() == {"2026-11-04": 3, "2026-10-03": 3, "2026-10-02": 3}
    assert not idx.status().ready and idx.status().pending_files == 1
    await idx.index_once()
    assert idx.reader().days()["2026-10-01"] == 3 and idx.status().ready


async def test_gz_files_are_read_once(env):
    idx, logs, _ = env
    write_gz(logs, "2026-10-30", [ev("2026-10-30T09:00:00.000+09:00", "system", i=i) for i in range(2)])
    assert await idx.index_once() == 2 and await idx.index_once() == 0


async def test_truncated_file_is_reread_without_duplicates_and_reported(env):
    idx, logs, log = env
    lines = [ev(f"2026-11-04T13:00:0{i}.000+09:00", "system", i=i) for i in range(3)]
    write_lines(logs, "2026-11-04", lines); await idx.index_once()
    (logs / "2026-11-04.jsonl").write_bytes(lines[0] + b"\n" + ev("2026-11-04T13:30:00.000+09:00", "system", i=9) + b"\n")
    assert await idx.index_once() == 1 and idx.reader().summary().rows == 4
    assert sys_events(log, "logindex.file_truncated")[0]["file"] == "2026-11-04.jsonl"


async def test_bad_lines_are_skipped_counted_and_reported_once(env):
    idx, logs, log = env
    good = ev("2026-11-04T13:00:00.000+09:00", "system")
    (logs / "2026-11-04.jsonl").write_bytes(b"{broken\n" + good + b"\n[]\n")
    assert await idx.index_once() == 1
    assert idx.status().bad_lines == 2 and [e["count"] for e in sys_events(log, "logindex.bad_lines")] == [2]


async def test_rollups_match_rows(env, tmp_path):
    idx, logs, _ = env
    write_lines(logs, "2026-11-04", [ev(f"2026-11-04T13:{i:02d}:00.000+09:00", "activity.window", user=f"u{i % 2}") for i in range(7)])
    await idx.index_once()
    with closing(sqlite3.connect(tmp_path / "index.db")) as c:
        assert c.execute("SELECT SUM(n) FROM counts_min").fetchone()[0] == 7
        assert c.execute("SELECT SUM(n) FROM counts_hour").fetchone()[0] == 7
        assert c.execute("SELECT COUNT(*) FROM events_fts").fetchone()[0] == 7


async def test_version_mismatch_rebuilds_from_jsonl(tmp_path, clock):
    logs = tmp_path / "logs"; logs.mkdir()
    write_lines(logs, "2026-11-04", [ev("2026-11-04T13:00:00.000+09:00", "system")])
    idx = LogIndex(tmp_path / "index.db", logs, clock, ListLog()); await idx.start(run_loop=False)
    await idx.index_once(); await idx.stop()
    # closing(): on Windows a connection left open would keep the rebuild from deleting the file
    with closing(sqlite3.connect(tmp_path / "index.db")) as c:
        c.execute(f"PRAGMA user_version = {INDEX_SCHEMA_VERSION + 7}")
    log = ListLog()
    idx2 = LogIndex(tmp_path / "index.db", logs, clock, log); await idx2.start(run_loop=False)
    assert idx2.reader().summary().rows == 0 and sys_events(log, "logindex.rebuilt")[0]["reason"] == "schema"
    await idx2.index_once(); assert idx2.reader().summary().rows == 1
    await idx2.stop()


async def test_flush_listener_wakes_the_indexer(tmp_path, clock):
    logs = tmp_path / "logs"; logs.mkdir()
    w = LogWriter(DailyJsonlWriter(logs), clock, flush_interval=0.01); await w.start()
    idx = LogIndex(tmp_path / "index.db", logs, clock, w, poll_sec=60); await idx.start()
    w.add_flush_listener(idx.wake)
    w.emit("system", event="hello"); await w.flush()
    await eventually(lambda: idx.status().rows >= 1)
    await idx.stop(); await w.stop()


def test_reindex_command(tmp_path):
    write_lines(tmp_path / "logs", "2026-11-04", [ev("2026-11-04T13:00:00.000+09:00", "system", i=i) for i in range(4)])
    assert main(["reindex", "--root", str(tmp_path)]) == 0
    with closing(sqlite3.connect(tmp_path / "data" / "index.db")) as c:
        assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 4


# --- beyond the plan's tests ---------------------------------------------------------------------


async def test_readers_on_every_thread_are_closed_so_a_rebuild_can_delete_the_file(tmp_path, clock):
    logs = tmp_path / "logs"
    write_lines(logs, "2026-11-04", [ev("2026-11-04T13:00:00.000+09:00", "system")])
    idx = LogIndex(tmp_path / "index.db", logs, clock, ListLog()); await idx.start(run_loop=False)
    await idx.index_once()
    assert idx.reader().summary().rows == 1  # a reader on the loop thread
    assert (await asyncio.to_thread(idx.reader().summary)).rows == 1  # and one on a worker thread
    await idx.stop()
    with closing(sqlite3.connect(tmp_path / "index.db")) as c:
        c.execute(f"PRAGMA user_version = {INDEX_SCHEMA_VERSION + 1}")
    log = ListLog()
    idx2 = LogIndex(tmp_path / "index.db", logs, clock, log); await idx2.start(run_loop=False)
    try:
        assert idx2.reader().summary().rows == 0
        assert [e["reason"] for e in sys_events(log, "logindex.rebuilt")] == ["schema"]
    finally:
        await idx2.stop()


def test_reader_reopens_after_close_all(tmp_path):
    conn, _ = prepare_index(tmp_path / "x.db"); conn.close()
    reader = IndexReader(tmp_path / "x.db")
    assert reader.summary().rows == 0
    reader.close_all()
    assert reader.summary().rows == 0 and reader.days() == {}
    reader.close_all()


async def test_reader_summary_days_and_count_before_day(env):
    idx, logs, _ = env
    write_lines(logs, "2026-11-02", [ev("2026-11-02T10:00:00.000+09:00", "system", i=i) for i in range(2)])
    write_lines(logs, "2026-11-04", [ev("2026-11-04T10:00:00.000+09:00", "system", i=i) for i in range(3)])
    await idx.index_once(); await idx.index_once()
    s = idx.reader().summary()
    assert (s.rows, s.oldest_day, s.newest_day) == (5, "2026-11-02", "2026-11-04")
    assert idx.reader().days() == {"2026-11-02": 2, "2026-11-04": 3}
    r = idx.reader()
    assert (r.count_before_day("2026-11-02"), r.count_before_day("2026-11-03"), r.count_before_day("2026-11-05")) == (0, 2, 5)


async def test_status_reports_pending_work_and_ready_once(env, clock):
    idx, logs, log = env
    paths = {}
    for day in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-11-04"):
        paths[day] = write_lines(logs, day, [ev(f"{day}T10:00:0{i}.000+09:00", "system", i=i) for i in range(3)])
    assert idx.status().ready is False and idx.status().rows == 0
    await idx.index_once()
    st = idx.status()
    assert (st.files, st.pending_files, st.rows) == (4, 1, 9)
    assert st.pending_bytes == paths["2026-10-01"].stat().st_size
    assert (st.oldest_day, st.newest_day, st.last_indexed_at) == ("2026-10-02", "2026-11-04", clock.now())
    assert sys_events(log, "logindex.ready") == []
    await idx.index_once(); await idx.index_once()
    st = idx.status()
    assert (st.ready, st.pending_files, st.pending_bytes, st.rows, st.oldest_day) == (True, 0, 0, 12, "2026-10-01")
    ready = sys_events(log, "logindex.ready")
    assert len(ready) == 1 and ready[0]["rows"] == 12 and isinstance(ready[0]["duration_ms"], int)


async def test_a_backlog_file_is_resumed_mid_file_across_cycles(env):
    idx, logs, _ = env
    write_lines(logs, "2026-10-01", [ev(f"2026-10-01T10:00:{i:02d}.000+09:00", "system", i=i) for i in range(10)])
    write_gz(logs, "2026-09-30", [ev(f"2026-09-30T10:00:{i:02d}.000+09:00", "system", i=i) for i in range(10)])
    # budget 4, batches of 3: each cycle stops after the batch that reaches the budget
    assert [await idx.index_once() for _ in range(5)] == [6, 4, 6, 4, 0]
    assert idx.reader().days() == {"2026-10-01": 10, "2026-09-30": 10} and idx.status().ready


async def test_realtime_files_are_read_to_the_end_regardless_of_the_budget(env):
    idx, logs, _ = env
    write_lines(logs, "2026-11-03", [ev(f"2026-11-03T10:00:{i:02d}.000+09:00", "system", i=i) for i in range(8)])
    write_lines(logs, "2026-11-04", [ev(f"2026-11-04T10:00:{i:02d}.000+09:00", "system", i=i) for i in range(8)])
    assert await idx.index_once() == 16 and idx.status().ready


async def test_plain_and_gz_of_the_same_day_share_the_dedup_key(env):
    idx, logs, _ = env
    lines = [ev(f"2026-10-20T10:00:0{i}.000+09:00", "system", i=i) for i in range(4)]
    write_gz(logs, "2026-10-20", lines[:3])
    write_lines(logs, "2026-10-20", lines[1:])  # a late plain file overlapping the compressed one
    await idx.index_once(); await idx.index_once()
    assert idx.reader().days() == {"2026-10-20": 4}


async def test_rollup_users_are_case_insensitive_and_none_is_empty(env, tmp_path):
    idx, logs, _ = env
    write_lines(logs, "2026-11-04", [
        ev("2026-11-04T13:00:01.000+09:00", "activity.window", user="Alice"),
        ev("2026-11-04T13:00:02.000+09:00", "activity.window", user="alice"),
        ev("2026-11-04T13:00:03.000+09:00", "system", event="x"),
    ])
    await idx.index_once()
    with closing(sqlite3.connect(tmp_path / "index.db")) as c:
        rows = c.execute("SELECT cat, user, n FROM counts_min ORDER BY cat").fetchall()
    assert [(cat, user.lower(), n) for cat, user, n in rows] == [("activity.window", "alice", 2), ("system", "", 1)]


async def test_truncation_report_names_the_offsets_and_resets_the_counts(env):
    idx, logs, log = env
    path = write_lines(logs, "2026-11-04", [b"{bad", ev("2026-11-04T13:00:00.000+09:00", "system", i=1)])
    await idx.index_once()
    before = path.stat().st_size
    path.write_bytes(b"{bad\n")
    await idx.index_once()
    assert sys_events(log, "logindex.file_truncated") == [{"event": "logindex.file_truncated", "file": "2026-11-04.jsonl", "before": before, "after": 5}]
    assert idx.status().bad_lines == 1 and idx.reader().summary().rows == 1


async def test_state_rows_of_removed_files_are_dropped_but_their_rows_stay(env, tmp_path):
    idx, logs, _ = env
    path = write_lines(logs, "2026-10-01", [ev("2026-10-01T10:00:00.000+09:00", "system")])
    await idx.index_once()
    path.unlink()
    await idx.index_once()
    with closing(sqlite3.connect(tmp_path / "index.db")) as c:
        assert c.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
    assert idx.reader().summary().rows == 1 and idx.status().files == 0 and idx.status().ready


async def test_rebuilt_is_logged_for_a_new_index_only_when_logs_exist(tmp_path, clock):
    empty_log = ListLog()
    idx = LogIndex(tmp_path / "a" / "index.db", tmp_path / "a" / "logs", clock, empty_log)
    await idx.start(run_loop=False); await idx.stop()
    assert sys_events(empty_log, "logindex.rebuilt") == []
    logs = tmp_path / "b" / "logs"
    write_lines(logs, "2026-11-04", [ev("2026-11-04T13:00:00.000+09:00", "system")])
    log = ListLog()
    idx = LogIndex(tmp_path / "b" / "index.db", logs, clock, log)
    await idx.start(run_loop=False)
    try:
        assert [e["reason"] for e in sys_events(log, "logindex.rebuilt")] == ["new"]
        assert idx.status().rebuilding and not idx.status().ready
        await idx.index_once()
        assert idx.status().ready and not idx.status().rebuilding
    finally:
        await idx.stop()
    log = ListLog()
    idx = LogIndex(tmp_path / "b" / "index.db", logs, clock, log)
    await idx.start(run_loop=False)
    try:  # reopened with a matching schema: nothing rebuilt, and rows already there
        assert sys_events(log, "logindex.rebuilt") == [] and not idx.status().rebuilding
        assert idx.status().rows == 1
    finally:
        await idx.stop()


async def test_the_loop_reports_a_failing_cycle_once_and_keeps_going(tmp_path, clock):
    logs = tmp_path / "logs"
    write_lines(logs, "2026-11-04", [ev("2026-11-04T13:00:00.000+09:00", "system")])
    log = ListLog()
    idx = LogIndex(tmp_path / "index.db", logs, clock, log, poll_sec=0.01)
    real = idx.index_once
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) <= 3:
            raise RuntimeError("disk on fire")
        return await real()

    idx.index_once = flaky
    await idx.start()
    try:
        await eventually(lambda: idx.status().ready)
    finally:
        await idx.stop()
    failed = sys_events(log, "logindex.cycle_failed")
    assert len(failed) == 1 and "disk on fire" in failed[0]["error"]
    assert len(calls) >= 4 and idx.status().rows == 1


async def test_cancelling_run_exclusive_waits_for_the_thread(env):
    idx, _, _ = env
    assert await idx.run_exclusive(lambda c: c.execute("SELECT 41 + 1").fetchone()[0]) == 42
    started = threading.Event()
    result = {}

    def slow(conn):
        started.set(); time.sleep(0.2)
        result["v"] = conn.execute("SELECT 1").fetchone()[0]

    task = asyncio.create_task(idx.run_exclusive(slow))
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert result == {"v": 1}  # the connection stayed usable until the thread was done
    await idx.stop()
    with pytest.raises(RuntimeError):
        await idx.run_exclusive(lambda c: 1)


async def test_services_have_an_index_that_index_all_fills(services):
    services.log.emit("system", event="hello")
    await index_all(services)
    assert services.log_index.reader().summary().rows == 1 and services.log_index.status().ready


def test_reindex_replaces_the_existing_index_and_prints_counts(tmp_path, capsys):
    write_lines(tmp_path / "logs", "2026-11-03", [ev("2026-11-03T13:00:00.000+09:00", "system", i=i) for i in range(2)])
    write_gz(tmp_path / "logs", "2026-10-03", [ev("2026-10-03T13:00:00.000+09:00", "system", i=i) for i in range(3)])
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "index.db").write_bytes(b"not a database at all")
    (tmp_path / "data" / "index.db-wal").write_bytes(b"stale")
    assert main(["reindex", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "indexed 5 rows from 2 files\n"
    assert not (tmp_path / "data" / "index.db-wal").exists()  # removed with the old index
    with closing(sqlite3.connect(tmp_path / "data" / "index.db")) as c:
        assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 5
