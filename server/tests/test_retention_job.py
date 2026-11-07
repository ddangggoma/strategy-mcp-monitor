import asyncio
import gzip
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from app.clock import to_kst_iso
from app.logstore.query import LogFilter
from app.logstore.retention import RetentionJob, compress_cutoff, preview
from tests.log_helpers import ev, index_all, write_gz, write_lines
from tests.mcp_helpers import make_user, seed_mcp
from tests.test_auth_api import audit_events, bootstrap, login
from tests.winfakes import eventually

DAYS = ["2026-10-25", "2026-10-28", "2026-10-29", "2026-11-03", "2026-11-04"]


async def seed_days(services):
    for d in DAYS:
        write_lines(services.paths.logs_dir, d, [ev(f"{d}T10:00:0{i}.000+09:00", "system", event="x", i=i) for i in range(2)])
    await index_all(services)


def fts_and_events(services):
    with closing(sqlite3.connect(services.paths.index_db_path)) as c:
        return c.execute("SELECT COUNT(*) FROM events_fts").fetchone()[0], c.execute("SELECT COUNT(*) FROM events").fetchone()[0]


async def test_purge_matches_the_preview(services):
    await seed_days(services)
    services.settings.update({"log_retention_days": 7, "log_compress_after_days": 7})
    p = preview(services.paths.logs_dir, date(2026, 11, 4), 7)
    res = await services.retention.run_once("manual")
    assert sorted(res.deleted_files) == ["2026-10-25.jsonl", "2026-10-28.jsonl"] and res.deleted_bytes == p.delete_bytes
    assert (res.deleted_from, res.deleted_to, res.cutoff) == (p.delete_from, p.delete_to, p.cutoff) and res.index_rows == 4
    days = services.log_index.reader().days()
    assert "2026-10-28" not in days and days["2026-10-29"] == 2 and res.errors == []
    fts, events = fts_and_events(services); assert fts == events


async def test_compresses_old_indexed_files_and_keeps_them_searchable(services):
    await seed_days(services)
    services.settings.update({"log_retention_days": 180, "log_compress_after_days": 3})
    res = await services.retention.run_once("manual")
    assert sorted(res.compressed) == ["2026-10-25.jsonl", "2026-10-28.jsonl", "2026-10-29.jsonl"]
    logs = services.paths.logs_dir
    assert (logs / "2026-10-29.jsonl.gz").exists() and not (logs / "2026-10-29.jsonl").exists()
    assert (logs / "2026-11-03.jsonl").exists()
    await services.log_index.index_once()
    assert services.log_index.reader().days()["2026-10-29"] == 2
    assert gzip.decompress((logs / "2026-10-29.jsonl.gz").read_bytes()).count(b"\n") == 2


async def test_compress_skips_files_not_fully_indexed(services):
    write_lines(services.paths.logs_dir, "2026-10-20", [ev("2026-10-20T10:00:00.000+09:00", "system")])
    services.settings.update({"log_compress_after_days": 3})
    res = await services.retention.run_once("manual")
    assert res.skipped_compress == ["2026-10-20.jsonl"] and (services.paths.logs_dir / "2026-10-20.jsonl").exists()


async def test_an_old_file_with_a_torn_last_line_is_still_compressed(services):
    # plan review minor 9: the fragment after the last newline of a file nobody writes any more is
    # indexed as its (bad) last line, so the file counts as fully indexed and is gzipped
    logs = services.paths.logs_dir
    write_lines(logs, "2026-10-29", [ev("2026-10-29T10:00:00.000+09:00", "system", event="ok")])
    with open(logs / "2026-10-29.jsonl", "ab") as fh:
        fh.write(b'{"ts": "2026-10-29T10:00:01.000+09:00", "cat": "sys')  # a crash mid-write
    await index_all(services)
    state = await services.log_index.file_state("2026-10-29.jsonl")
    assert state.offset < (logs / "2026-10-29.jsonl").stat().st_size  # the fragment waits forever
    services.settings.update({"log_compress_after_days": 3})
    res = await services.retention.run_once("manual")
    assert res.compressed == ["2026-10-29.jsonl"] and res.skipped_compress == []
    assert gzip.decompress((logs / "2026-10-29.jsonl.gz").read_bytes()).endswith(b'"cat": "sys')
    await services.log_index.index_once()
    assert services.log_index.reader().days()["2026-10-29"] == 1
    bad = [e for e in await audit_events(services, "system") if e.get("event") == "logindex.bad_lines"]
    assert [(e["file"], e["count"]) for e in bad] == [("2026-10-29.jsonl", 1)]


async def test_an_old_file_with_unindexed_complete_lines_is_left_to_the_indexer(services):
    logs = services.paths.logs_dir
    write_lines(logs, "2026-10-29", [ev("2026-10-29T10:00:00.000+09:00", "system", event="ok")])
    await index_all(services)
    write_lines(logs, "2026-10-29", [ev("2026-10-29T11:00:00.000+09:00", "system", event="late")])  # not indexed yet
    services.settings.update({"log_compress_after_days": 3})
    res = await services.retention.run_once("manual")
    assert res.skipped_compress == ["2026-10-29.jsonl"] and (logs / "2026-10-29.jsonl").exists()


async def test_late_plain_file_is_merged_into_the_existing_gz(services):
    await seed_days(services); services.settings.update({"log_compress_after_days": 3})
    await services.retention.run_once("manual")
    write_lines(services.paths.logs_dir, "2026-10-29", [ev("2026-10-29T23:59:59.000+09:00", "system", event="late")])
    await index_all(services)
    res = await services.retention.run_once("manual")
    logs = services.paths.logs_dir
    assert res.compressed == ["2026-10-29.jsonl"] and not (logs / "2026-10-29.jsonl").exists()
    assert gzip.decompress((logs / "2026-10-29.jsonl.gz").read_bytes()).count(b"\n") == 3
    await services.log_index.index_once()
    assert services.log_index.reader().days()["2026-10-29"] == 3


async def test_removals_are_announced_to_the_tamper_scanner(services):
    await seed_days(services); services.tamper_scanner.scan()
    services.settings.update({"log_retention_days": 7, "log_compress_after_days": 3})
    await services.retention.run_once("manual"); services.tamper_scanner.scan()
    assert [r for r in services.tamper.recent(50) if r["event"] in ("log_file_removed", "log_file_truncated")] == []


async def test_purges_expired_rows_in_every_table(services):
    db, now = services.db, services.clock.now()  # 2026-11-04T05:00Z
    old_utc, new_utc = (now - timedelta(days=200)).isoformat(), (now - timedelta(days=1)).isoformat()
    live_utc = (now - timedelta(minutes=1)).isoformat()
    old_kst, new_kst = to_kst_iso(now - timedelta(hours=2)), to_kst_iso(now - timedelta(seconds=30))
    u = make_user(services, "u@x.com")
    sess = ("INSERT INTO auth_sessions (id_hash, user_id, channel, csrf_token, created_at, last_seen_at)"
            " VALUES (?, ?, 'local', 'c', ?, ?)")
    db.execute(sess, ("old", u.id, old_utc, old_utc)); db.execute(sess, ("live", u.id, live_utc, live_utc))
    otp = "INSERT INTO otp_codes (email, code_hash, expires_at, attempts, last_sent_at) VALUES (?, ?, NULL, 0, ?)"
    db.execute(otp, ("ghost@x.com", None, old_kst)); db.execute(otp, ("u@x.com", "h", old_kst))
    for table, col in (("otp_failures", "email"), ("otp_verify_ip", "ip"), ("otp_ip_requests", "ip")):
        db.execute(f"INSERT INTO {table} ({col}, at) VALUES ('k', ?), ('k', ?)", (old_kst, new_kst))
    m = seed_mcp(services, u)
    for at in (old_utc, new_utc):
        db.execute("INSERT INTO mcp_transitions (mcp_id, at, from_state, to_state) VALUES (?, ?, 'HEALTHY', 'SUSPECT')", (m.id, at))
        db.execute("INSERT INTO mcp_actions (run_id, mcp_id, at, requested, kind, trigger, reason, status, duration_ms)"
                   " VALUES ('r', ?, ?, 'start', 'start', 'manual', 'manual', 'ok', 1)", (m.id, at))
    conn = ("INSERT INTO rdp_connections (session_id, kind, user, protocol, connected_at, ended_at, end_reason)"
            " VALUES (2, 'logon', 'hong', 'rdp', ?, ?, ?)")
    old_conn = db.execute(conn, (old_utc, old_utc, "logoff"))
    db.execute(conn, (old_utc, None, None)); db.execute(conn, (new_utc, new_utc, "logoff"))
    db.execute("INSERT INTO notice_displays (connection_id, session_id, user, kind, version, created_at)"
               " VALUES (?, 2, 'hong', 'logon', 0, ?)", (old_conn, old_utc))
    for at in (old_utc, new_utc):
        db.execute("INSERT INTO rdp_logon_failures (at, source) VALUES (?, 'eventlog:4625')", (at,))
    res = await services.retention.run_once("manual")
    assert res.db_rows == {"auth_sessions": 1, "otp_codes": 1, "otp_failures": 1, "otp_verify_ip": 1, "otp_ip_requests": 1,
                           "mcp_actions": 1, "mcp_transitions": 1, "notice_displays": 1, "rdp_connections": 1,
                           "rdp_logon_failures": 1}
    assert [r["id_hash"] for r in db.query("SELECT id_hash FROM auth_sessions")] == ["live"]
    assert db.query("SELECT COUNT(*) AS n FROM rdp_connections WHERE ended_at IS NULL")[0]["n"] == 1
    assert [r["email"] for r in db.query("SELECT email FROM otp_codes")] == ["u@x.com"]


async def test_run_is_logged_and_audited(services):
    await seed_days(services); services.settings.update({"log_retention_days": 7, "log_compress_after_days": 7})
    await services.retention.run_once("manual")
    purge = [e for e in await audit_events(services, "admin.audit") if e["action"] == "retention_purge"]
    assert len(purge) == 1 and purge[0]["result"] == "ok" and purge[0]["actor_id"] is None
    assert (purge[0]["target"]["deleted_from"], purge[0]["target"]["files"]) == ("2026-10-25", 2)
    runs = [e for e in await audit_events(services, "system") if e.get("event") == "retention.run"]
    assert runs[-1]["index_rows"] == 4 and runs[-1]["reason"] == "manual"


async def test_lowering_retention_via_api_runs_the_job(local_client, services):
    services.retention.request_delay_sec = 0.01
    await seed_days(services); await bootstrap(local_client); await login(local_client, services)
    r = await local_client.put("/api/settings", json={"log_retention_days": 7, "log_compress_after_days": 7},
                               headers={"X-CSRF-Token": local_client.csrf})
    assert r.status_code == 200
    await eventually(lambda: not (services.paths.logs_dir / "2026-10-25.jsonl").exists())


async def test_preview_reports_index_rows(local_client, services):
    await seed_days(services); await bootstrap(local_client); await login(local_client, services)
    body = (await local_client.get("/api/settings/retention/preview", params={"days": 7})).json()
    assert body["delete_events"] == 4 and body["delete_files"] == 2


@pytest.mark.parametrize("now,want", [
    (datetime(2026, 11, 4, 5, 0, tzinfo=UTC), datetime(2026, 11, 4, 18, 30, tzinfo=UTC)),
    (datetime(2026, 11, 3, 18, 0, tzinfo=UTC), datetime(2026, 11, 3, 18, 30, tzinfo=UTC)),
    (datetime(2026, 11, 3, 18, 30, tzinfo=UTC), datetime(2026, 11, 4, 18, 30, tzinfo=UTC))])
def test_next_run_is_0330_kst(services, now, want):
    assert services.retention.next_run_at(now) == want


# --- additional coverage (carries from Tasks 3 and 4, preflight F14 and F23) ---


def test_compress_cutoff_keeps_at_least_two_days():
    today = date(2026, 11, 4)
    assert compress_cutoff(today, 1) == compress_cutoff(today, 2) == date(2026, 11, 3)
    assert compress_cutoff(today, 3) == date(2026, 11, 2) and compress_cutoff(today, 30) == date(2026, 10, 6)


async def test_purge_keeps_rollup_histograms_equal_to_a_scan(services):
    logs = services.paths.logs_dir
    for d in ("2026-10-27", "2026-10-28", "2026-10-29"):
        write_lines(logs, d, [ev(f"{d}T{h:02d}:{m:02d}:00.000+09:00", cat, user=user)
                              for h in (0, 9, 23) for m in (0, 1, 59)
                              for cat, user in (("session", "CORP\\Hong"), ("session", "corp\\hong"), ("system", None))])
    # a line filed under 10-29 whose time is on 10-28: the purge must remove exactly the rows it deletes
    write_lines(logs, "2026-10-29", [ev("2026-10-28T23:59:30.000+09:00", "session", user="CORP\\Hong", late=True)])
    await index_all(services)
    services.settings.update({"log_retention_days": 7, "log_compress_after_days": 7})
    res = await services.retention.run_once("manual")
    assert res.index_rows == 54 and res.errors == []
    r = services.log_index.reader()
    f = LogFilter(from_ms=int(datetime(2026, 10, 26, 15, tzinfo=UTC).timestamp() * 1000),  # 10-27 00:00 KST
                  to_ms=int(datetime(2026, 10, 29, 15, tzinfo=UTC).timestamp() * 1000))    # 10-30 00:00 KST
    scan_f = replace(f, to_ms=f.to_ms - 1)  # off the minute: forced onto the scan path
    for group in ("none", "cat", "user"):
        for buckets in (12, 72, 200):
            roll, scan = r.histogram(f, buckets, group), r.histogram(scan_f, buckets, group)
            assert (roll.source, scan.source) == ("rollup", "scan")
            assert roll.series == scan.series and roll.total == scan.total == 28
    assert r.users(f) == r.users(scan_f)
    with closing(sqlite3.connect(services.paths.index_db_path)) as c:
        assert c.execute("SELECT COUNT(*) FROM counts_min WHERE n <= 0").fetchone()[0] == 0
        assert c.execute("SELECT SUM(n) FROM counts_min").fetchone()[0] == 28
        assert c.execute("SELECT SUM(n) FROM counts_hour").fetchone()[0] == 28


async def test_delete_before_works_in_chunks_and_refreshes_the_status(services):
    for d in ("2026-10-20", "2026-10-21"):
        write_lines(services.paths.logs_dir, d, [ev(f"{d}T10:00:{i:02d}.000+09:00", "system", i=i) for i in range(7)])
    await index_all(services)
    assert services.log_index.status().rows == 14
    assert await services.log_index.delete_before("2026-10-21", chunk=3) == 7
    assert services.log_index.reader().days() == {"2026-10-21": 7}
    fts, events = fts_and_events(services); assert (fts, events) == (7, 7)
    await services.log_index.index_once()
    assert (services.log_index.status().rows, services.log_index.status().oldest_day) == (7, "2026-10-21")


async def test_file_state_and_rename_file(services):
    write_lines(services.paths.logs_dir, "2026-10-20", [ev("2026-10-20T10:00:00.000+09:00", "system")])
    await index_all(services)
    plain = await services.log_index.file_state("2026-10-20.jsonl")
    assert plain is not None and plain.offset == plain.size and plain.lines == 1
    assert await services.log_index.file_state("nope.jsonl") is None
    gz = write_gz(services.paths.logs_dir, "2026-10-20", [ev("2026-10-20T10:00:00.000+09:00", "system")])
    (services.paths.logs_dir / "2026-10-20.jsonl").unlink()
    await services.log_index.rename_file("2026-10-20.jsonl", "2026-10-20.jsonl.gz", plain.offset)
    st = await services.log_index.file_state("2026-10-20.jsonl.gz")
    assert st is not None and (st.offset, st.size, st.done, st.lines) == (plain.offset, gz.stat().st_size, True, 1)
    assert await services.log_index.file_state("2026-10-20.jsonl") is None


async def test_merge_does_not_duplicate_lines_already_in_the_gz(services):
    # A previous run wrote the gz but could not delete the plain file: merging again adds only new lines.
    a, b, c = (ev(f"2026-10-20T10:00:0{i}.000+09:00", "system", i=i) for i in range(3))
    write_gz(services.paths.logs_dir, "2026-10-20", [a, b])
    write_lines(services.paths.logs_dir, "2026-10-20", [a, b, c])
    await index_all(services)
    services.settings.update({"log_compress_after_days": 3})
    res = await services.retention.run_once("manual")
    assert res.compressed == ["2026-10-20.jsonl"] and res.errors == []
    assert gzip.decompress((services.paths.logs_dir / "2026-10-20.jsonl.gz").read_bytes()).splitlines() == [a, b, c]


async def test_compress_skips_when_the_gz_is_not_fully_indexed(services):
    write_gz(services.paths.logs_dir, "2026-10-20", [ev("2026-10-20T10:00:00.000+09:00", "system")])
    write_lines(services.paths.logs_dir, "2026-10-20", [ev("2026-10-20T11:00:00.000+09:00", "system")])
    await index_all(services)
    await services.log_index.run_exclusive(lambda c: c.execute("UPDATE files SET done = 0 WHERE name LIKE '%.gz'"))
    services.settings.update({"log_compress_after_days": 3})
    res = await services.retention.run_once("manual")
    assert res.compressed == [] and res.skipped_compress == ["2026-10-20.jsonl"]
    assert (services.paths.logs_dir / "2026-10-20.jsonl").exists()


async def test_a_file_that_cannot_be_deleted_is_reported_and_not_hidden_from_the_scanner(services):
    await seed_days(services); services.tamper_scanner.scan()
    services.settings.update({"log_retention_days": 7, "log_compress_after_days": 7})
    held = (services.paths.logs_dir / "2026-10-25.jsonl").open("rb")  # Windows: cannot be deleted while open
    try:
        res = await services.retention.run_once("manual")
    finally:
        held.close()
    assert res.deleted_files == ["2026-10-28.jsonl"] and (res.deleted_from, res.deleted_to) == (date(2026, 10, 28),) * 2
    assert len(res.errors) == 1 and res.errors[0].startswith("files: 2026-10-25.jsonl: PermissionError")
    assert res.compressed == [] and not (services.paths.logs_dir / "2026-10-25.jsonl.gz").exists()
    (services.paths.logs_dir / "2026-10-25.jsonl").unlink()  # a real deletion later must be reported
    services.tamper_scanner.scan()
    assert [r["file"] for r in services.tamper.recent(50) if r["event"] == "log_file_removed"] == ["2026-10-25.jsonl"]
    purge = [e for e in await audit_events(services, "admin.audit") if e["action"] == "retention_purge"]
    assert purge[-1]["result"] == "error"


async def test_an_undeletable_expired_file_is_not_indexed_again(services):
    # plan review minor 14: rows of an expired day must not come back through a file that could not
    # be deleted and was not fully indexed yet
    await seed_days(services)
    write_lines(services.paths.logs_dir, "2026-10-25", [ev("2026-10-25T11:00:00.000+09:00", "system", event="late")])
    services.settings.update({"log_retention_days": 7, "log_compress_after_days": 7})
    held = (services.paths.logs_dir / "2026-10-25.jsonl").open("rb")
    try:
        res = await services.retention.run_once("manual")
    finally:
        held.close()
    assert "2026-10-25.jsonl" not in res.deleted_files and (services.paths.logs_dir / "2026-10-25.jsonl").exists()
    await services.log_index.index_once()
    assert "2026-10-25" not in services.log_index.reader().days()
    assert services.log_index.status().pending_files == 0  # not counted as work either


async def test_nothing_to_purge_is_logged_but_not_audited(services):
    res = await services.retention.run_once("schedule")
    assert (res.deleted_files, res.index_rows, res.compressed, res.errors) == ([], 0, [], [])
    assert [e for e in await audit_events(services, "admin.audit") if e["action"] == "retention_purge"] == []
    runs = [e for e in await audit_events(services, "system") if e.get("event") == "retention.run"]
    assert runs[-1]["deleted_from"] is None and runs[-1]["cutoff"] == "2026-05-09"
    last = await services.log_index.run_exclusive(
        lambda c: c.execute("SELECT value FROM meta WHERE key = 'retention_last_run'").fetchone()[0])
    assert last == "2026-11-04"


def _job(services, **kw):
    return RetentionJob(services.paths, services.db, services.settings, services.log_index, services.log,
                        services.audit, services.clock, services.tamper_scanner, **kw)


async def test_start_runs_a_missed_day_after_the_startup_delay(services):
    await seed_days(services); services.settings.update({"log_retention_days": 7, "log_compress_after_days": 7})
    job = _job(services, startup_delay_sec=0.01)
    await job.start()
    try:
        await eventually(lambda: not (services.paths.logs_dir / "2026-10-25.jsonl").exists())
    finally:
        await job.stop()
    runs = [e for e in await audit_events(services, "system") if e.get("event") == "retention.run"]
    assert [r["reason"] for r in runs] == ["startup"]


async def test_start_skips_the_startup_run_when_today_already_ran(services):
    await services.retention.run_once("manual")  # records retention_last_run = 2026-11-04
    await seed_days(services); services.settings.update({"log_retention_days": 7, "log_compress_after_days": 7})
    job = _job(services, startup_delay_sec=0)
    await job.start()
    try:
        await asyncio.sleep(0.2)
    finally:
        await job.stop()
    assert (services.paths.logs_dir / "2026-10-25.jsonl").exists()


async def test_request_run_is_coalesced_and_stop_cancels_the_delay(services):
    await seed_days(services); services.settings.update({"log_retention_days": 7, "log_compress_after_days": 7})
    job = _job(services, request_delay_sec=60)
    job.request_run(); job.request_run()
    assert len(job._tasks) == 1
    await asyncio.wait_for(job.stop(), 1)
    assert job._tasks == set() and (services.paths.logs_dir / "2026-10-25.jsonl").exists()
    job.request_run()  # stopped: ignored
    assert job._tasks == set()


async def test_a_requested_run_keeps_the_day_it_was_confirmed_on(services):
    # plan review minor 8: a retention change confirmed at 23:59:59 KST runs ~5 s later, after
    # midnight; it must delete what the confirmed preview showed, not one more day
    await seed_days(services); services.settings.update({"log_retention_days": 7, "log_compress_after_days": 7})
    job = _job(services, request_delay_sec=0.2)
    job.request_run("settings")  # 2026-11-04 14:00 KST: cutoff 2026-10-29
    services.clock.advance(10 * 3600 + 5)  # 2026-11-05 00:00:05 KST before the run starts
    await eventually(lambda: not (services.paths.logs_dir / "2026-10-28.jsonl").exists())
    await eventually(lambda: not job._tasks)
    assert (services.paths.logs_dir / "2026-10-29.jsonl").exists()  # the 11-05 cutoff would delete it
    await services.log.flush()  # the run logged after midnight: the 11-05 file
    runs = [json.loads(x) for x in (services.paths.logs_dir / "2026-11-05.jsonl").read_text("utf-8").splitlines()]
    assert [(r["reason"], r["cutoff"]) for r in runs if r.get("event") == "retention.run"] == [("settings", "2026-10-29")]
    # a scheduled run (no confirmed preview) uses its own day
    res = await job.run_once("schedule")
    assert res.cutoff == date(2026, 10, 30) and not (services.paths.logs_dir / "2026-10-29.jsonl").exists()
    await job.stop()


async def test_stop_waits_for_a_run_in_progress(services, monkeypatch):
    await seed_days(services); services.settings.update({"log_retention_days": 7, "log_compress_after_days": 7})
    original = services.log_index.delete_before

    async def slow_delete_before(day, chunk=5000):
        await asyncio.sleep(0.2)
        return await original(day, chunk)

    monkeypatch.setattr(services.log_index, "delete_before", slow_delete_before)
    job = _job(services, request_delay_sec=0)
    job.request_run("settings")
    await eventually(lambda: job._lock.locked())
    await job.stop()
    assert services.log_index.reader().days().get("2026-10-28") is None
    runs = [e for e in await audit_events(services, "system") if e.get("event") == "retention.run"]
    assert [(r["reason"], r["index_rows"]) for r in runs] == [("settings", 4)]


async def test_a_failing_run_is_logged_and_the_job_goes_on(services, monkeypatch):
    def broken():
        raise RuntimeError("settings unreadable")

    monkeypatch.setattr(services.settings, "get", broken)
    job = _job(services, request_delay_sec=0)
    job.request_run("settings")
    await eventually(lambda: not job._tasks)
    failed = [e for e in await audit_events(services, "system") if e.get("event") == "retention.failed"]
    assert failed[0]["error"] == "RuntimeError: settings unreadable"
    job.request_run("settings")
    assert len(job._tasks) == 1
    await job.stop()


@pytest.mark.parametrize("body,runs", [
    ({"log_retention_days": 90}, 1),
    ({"log_retention_days": 180}, 0),           # unchanged
    ({"log_retention_days": 365}, 0),           # raised: nothing more to delete
    ({"log_compress_after_days": 10}, 1),
    ({"ping_interval_sec": 10}, 0),
])
async def test_settings_changes_that_request_a_run(local_client, services, monkeypatch, body, runs):
    calls = []
    monkeypatch.setattr(services.retention, "request_run", lambda reason="settings": calls.append(reason))
    await bootstrap(local_client); await login(local_client, services)
    r = await local_client.put("/api/settings", json=body, headers={"X-CSRF-Token": local_client.csrf})
    assert r.status_code == 200 and calls == ["settings"] * runs
