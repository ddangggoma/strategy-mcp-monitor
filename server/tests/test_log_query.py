import base64
import json
import random
import sqlite3
import threading
from contextlib import closing
from dataclasses import replace
from datetime import datetime

import pytest
import pytest_asyncio

from app.logstore import indexer as indexer_mod
from app.logstore.fts import InvalidQuery
from app.logstore.index_db import open_reader
from app.logstore.indexer import IndexReader, LogIndex
from app.logstore.query import (
    MAX_PAGE,
    MAX_SPAN_MS,
    Cursor,
    LogFilter,
    bucket_start,
    choose_bucket,
    decode_cursor,
    encode_cursor,
    page_queries,
)
from tests.log_helpers import ev, write_lines
from tests.winfakes import ListLog

USERS = ["CORP\\hong", "CORP\\kim", "a@x.com"]
CATS = ["activity.command", "activity.window", "auth"]


def ms(kst: str) -> int:
    return int(datetime.fromisoformat(kst).timestamp() * 1000)


def F(**kw) -> LogFilter:
    return LogFilter(from_ms=ms("2026-11-04T13:00:00+09:00"), to_ms=ms("2026-11-04T14:00:00+09:00"), **kw)


@pytest_asyncio.fixture
async def reader(tmp_path, clock):
    logs = tmp_path / "logs"; lines = []
    for i in range(30):
        cat, user = CATS[i % 3], USERS[i % 3]
        extra = {"email": user, "event": "login", "ok": i % 2 == 0} if cat == "auth" else {"user": user, "session_id": 2}
        lines.append(ev(f"2026-11-04T13:{i:02d}:00.000+09:00", cat, text="cmd-7 zebra" if i == 7 else f"cmd-{i}", **extra))
    write_lines(logs, "2026-11-04", lines)
    idx = LogIndex(tmp_path / "index.db", logs, clock, ListLog()); await idx.start(run_loop=False)
    await idx.index_once()
    yield idx.reader()
    await idx.stop()


def test_page_newest_first_with_cursor(reader):
    p1 = reader.page(F(), None, 10)
    assert [r.data["text"] for r in p1.rows][:2] == ["cmd-29", "cmd-28"] and p1.next_cursor
    p2 = reader.page(F(), decode_cursor(p1.next_cursor), 10)
    assert p2.rows[0].data["text"] == "cmd-19"
    p3 = reader.page(F(), decode_cursor(p2.next_cursor), 10)
    assert len(p3.rows) == 10 and p3.next_cursor is None


def test_filters_fan_out_and_merge(reader):
    rows = reader.page(F(users=("corp\\HONG", "a@x.com")), None, 100).rows
    assert len(rows) == 20 and [r.ts_ms for r in rows] == sorted((r.ts_ms for r in rows), reverse=True)
    assert {r.user.lower() for r in rows} == {"corp\\hong", "a@x.com"}
    assert len(reader.page(F(cats=("auth",), outcomes=("fail",)), None, 100).rows) == 5
    assert [r.data["text"] for r in reader.page(F(q="zeb"), None, 100).rows] == ["cmd-7 zebra"]
    assert len(reader.page(F(session_id=2, cats=("activity.window",)), None, 100).rows) == 10
    merged = reader.page(F(users=tuple(USERS)), None, 7)
    assert [r.data["text"] for r in merged.rows] == [f"cmd-{i}" for i in range(29, 22, -1)] and merged.next_cursor


def test_histogram_rollup_equals_scan(reader):
    h1 = reader.histogram(F(), buckets=6)
    assert (h1.source, h1.bucket_sec, h1.series) == ("rollup", 600, [(None, [10, 10, 10, 0, 0, 0])])
    h2 = reader.histogram(F(q="cmd"), buckets=6)
    assert h2.source == "scan" and h2.series == h1.series and h2.total == 30
    hc = reader.histogram(F(), buckets=6, group="cat")
    assert [k for k, _ in hc.series] == ["activity.command", "activity.window", "auth"]
    hu = reader.histogram(F(cats=("activity.command",)), buckets=6, group="user")
    assert hu.series == [("CORP\\hong", [4, 3, 3, 0, 0, 0])]


def test_users_facet_ignores_the_users_filter(reader):
    assert reader.users(F(users=("CORP\\hong",))) == [("a@x.com", 10), ("CORP\\hong", 10), ("CORP\\kim", 10)]
    assert reader.users(F(cats=("auth",))) == [("a@x.com", 10)]


def test_iter_rows_streams_in_chunks(reader):
    rows = list(reader.iter_rows(F(), limit=25, chunk=10))
    assert len(rows) == 25 and rows[0].data["text"] == "cmd-29"


@pytest.mark.parametrize("span_ms,max_b,want", [(3_600_000, 60, 60), (7 * 86_400_000, 60, 10800),
                                                (30 * 86_400_000, 60, 43200), (180 * 86_400_000, 60, 259200)])
def test_choose_bucket(span_ms, max_b, want):
    assert choose_bucket(span_ms, max_b) == want


def test_cursor_round_trip_and_validation():
    assert decode_cursor(encode_cursor(Cursor(1793000000000, 42))) == Cursor(1793000000000, 42)
    for bad in ("!!", "W10", encode_cursor(Cursor(1, 2))[:-3]):
        with pytest.raises(InvalidQuery):
            decode_cursor(bad)
    with pytest.raises(InvalidQuery):
        F(cats=("nope",))
    with pytest.raises(InvalidQuery):
        LogFilter(from_ms=5, to_ms=5)
    with pytest.raises(InvalidQuery):
        F(users=tuple(f"u{i}" for i in range(51)))


# -- beyond the plan's tests ------------------------------------------------------------------------

def scan_of(f: LogFilter) -> LogFilter:
    """The same filter forced onto the scan path (``to`` off the minute; no row lies in that last ms)."""
    return replace(f, to_ms=f.to_ms - 1)


async def index_lines(tmp_path, clock, by_day: dict[str, list[bytes]]) -> LogIndex:
    logs = tmp_path / "logs"
    for day, lines in by_day.items():
        write_lines(logs, day, lines)
    idx = LogIndex(tmp_path / "index.db", logs, clock, ListLog()); await idx.start(run_loop=False)
    while not idx.status().ready:
        await idx.index_once()
    return idx


def b64(value: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def test_cursor_has_no_padding_and_rejects_other_shapes():
    s = encode_cursor(Cursor(1, 2))
    assert "=" not in s and decode_cursor(s) == Cursor(1, 2)
    for bad in (b64([1, 2, 3]), b64([True, 2]), b64([1.5, 2]), b64({"a": 1}), b64([1, 2 ** 63]), "", "é", "a" * 401):
        with pytest.raises(InvalidQuery):
            decode_cursor(bad)


def test_filter_validation():
    base = ms("2026-11-04T13:00:00+09:00")
    assert LogFilter(from_ms=base, to_ms=base + MAX_SPAN_MS).fts is None
    assert F(q="zeb  cmd").fts == '"zeb"* "cmd"*'
    assert F(q=" -- ").fts is None
    for kw in (dict(from_ms=base, to_ms=base + MAX_SPAN_MS + 1), dict(from_ms=base + 1, to_ms=base)):
        with pytest.raises(InvalidQuery):
            LogFilter(**kw)
    for kw in (dict(users=("",)), dict(users=("x" * 257,)), dict(events=tuple(f"e{i}" for i in range(21))),
               dict(events=("",)), dict(events=("e" * 65,)), dict(outcomes=("maybe",)),
               dict(channel="lan"), dict(q=" ".join(f"w{i}" for i in range(11)))):
        with pytest.raises(InvalidQuery):
            F(**kw)
    ok = F(users=tuple(f"u{i}" for i in range(50)), events=tuple(f"e{i}" for i in range(20)),
           outcomes=("ok", "fail"), channel="external")
    assert ok.channel == "external" and len(ok.users) == 50
    assert F(q="a") == F(q="a") and hash(F(q="a")) == hash(F(q="a"))


def test_page_limit_bounds(reader):
    for bad in (0, MAX_PAGE + 1):
        with pytest.raises(InvalidQuery):
            reader.page(F(), None, bad)
    assert len(reader.page(F(), None, MAX_PAGE).rows) == 30


def test_bucket_start_aligns_to_kst():
    t = ms("2026-11-04T13:37:00+09:00")
    assert bucket_start(t, 86400) == ms("2026-11-04T00:00:00+09:00")
    assert bucket_start(t, 43200) == ms("2026-11-04T12:00:00+09:00")
    assert bucket_start(t, 600) == ms("2026-11-04T13:30:00+09:00")


async def test_cursor_keeps_rows_of_the_same_millisecond(tmp_path, clock):
    lines = [ev("2026-11-04T13:10:00.000+09:00", "system", event=f"e{i}") for i in range(5)]
    idx = await index_lines(tmp_path, clock, {"2026-11-04": lines})
    try:
        seen, cursor = [], None
        while True:
            p = idx.reader().page(F(), cursor, 2)
            seen += [row.event for row in p.rows]
            if p.next_cursor is None:
                break
            cursor = decode_cursor(p.next_cursor)
        assert seen == [f"e{i}" for i in range(4, -1, -1)]
    finally:
        await idx.stop()


def test_more_filters(reader):
    assert reader.page(F(client_ip="10.9.9.9"), None, 10).rows == []
    assert [r.event for r in reader.page(F(events=("login",)), None, 100).rows] == ["login"] * 10
    assert reader.page(F(channel="local"), None, 100).rows == []
    # a cursor on a fan-out continues every value's query
    p1 = reader.page(F(users=("CORP\\hong", "CORP\\kim")), None, 5)
    p2 = reader.page(F(users=("CORP\\hong", "CORP\\kim")), decode_cursor(p1.next_cursor), 100)
    texts = [r.data["text"] for r in p1.rows + p2.rows]
    assert len(texts) == 20 and len(set(texts)) == 20 and p2.next_cursor is None
    # the same user twice (case differs) is one fan-out value, not duplicated rows
    assert len(reader.page(F(users=("CORP\\hong", "corp\\HONG")), None, 100).rows) == 10
    assert len(reader.page(F(cats=("auth", "auth")), None, 100).rows) == 10
    # a keyword next to another driving dimension is a residual condition
    assert [r.data["text"] for r in reader.page(F(users=("CORP\\kim",), q="zebra"), None, 10).rows] == ["cmd-7 zebra"]
    assert reader.page(F(users=("CORP\\hong",), q="zebra"), None, 10).rows == []
    row = reader.page(F(q="zebra"), None, 1).rows[0]
    assert (row.cat, row.event, row.user, row.session_id, row.client_ip, row.outcome) == (
        "activity.window", None, "CORP\\kim", 2, None, None)


async def test_histogram_groups_users_with_other_and_none(tmp_path, clock):
    lines = []
    for u in range(12):  # user U<u> has u + 1 rows
        lines += [ev(f"2026-11-04T13:{u:02d}:{s:02d}.000+09:00", "activity.window", user=f"U{u:02d}") for s in range(u + 1)]
    lines.append(ev("2026-11-04T13:50:00.000+09:00", "system", event="x"))
    lines.append(ev("2026-11-04T13:51:00.000+09:00", "activity.window", user="u11"))  # same user, other case
    idx = await index_lines(tmp_path, clock, {"2026-11-04": lines})
    try:
        r = idx.reader()
        h = r.histogram(F(), buckets=1, group="user")
        assert h.source == "rollup" and h.bucket_sec == 3600
        assert [k for k, _ in h.series] == ["U11", "U10", "U09", "U08", "U07", "U06", "U05", "U04", "U03", "U02",
                                            "__other__", None]
        assert dict(h.series)["U11"] == [13] and dict(h.series)["__other__"] == [3] and dict(h.series)[None] == [1]
        assert h.total == sum(range(1, 13)) + 2
        scan = r.histogram(scan_of(F()), buckets=1, group="user")
        assert scan.source == "scan" and scan.series == h.series
        assert r.histogram(F(events=("x",)), buckets=1, group="user").series == [(None, [1])]
        assert r.histogram(F(cats=("system",)), buckets=1, group="user").series == [(None, [1])]
        assert r.histogram(F(cats=("auth",)), buckets=1, group="cat").series == []
        assert r.histogram(F(cats=("auth",)), buckets=1).series == [(None, [0])]
        assert r.users(F(), limit=2) == [("U11", 13), ("U10", 11)]
    finally:
        await idx.stop()


async def test_rollup_and_scan_agree_off_the_hour(tmp_path, clock):
    """Minute edges around whole hours: the rollups (hours inside, minutes at the edges) equal the scan."""
    rnd = random.Random(7)
    by_day: dict[str, list[bytes]] = {}
    for day in ("2026-11-03", "2026-11-04"):
        by_day[day] = []
        for _ in range(400):
            cat = rnd.choice(["activity.window", "auth", "system"])
            extra = {"user": rnd.choice(USERS)} if cat != "system" else {}
            ts = f"{day}T{rnd.randrange(24):02d}:{rnd.randrange(60):02d}:{rnd.randrange(60):02d}.{rnd.randrange(1000):03d}+09:00"
            by_day[day].append(ev(ts, cat, n=rnd.randrange(10**9), **extra))
    idx = await index_lines(tmp_path, clock, by_day)
    try:
        r = idx.reader()
        f = LogFilter(ms("2026-11-03T05:17:00+09:00"), ms("2026-11-04T19:43:00+09:00"))
        for group in ("none", "cat", "user"):
            for buckets in (12, 60, 200):
                roll = r.histogram(f, buckets=buckets, group=group)
                scan = r.histogram(scan_of(f), buckets=buckets, group=group)
                assert (roll.source, scan.source) == ("rollup", "scan")
                assert (roll.bucket_sec, roll.starts_ms) == (scan.bucket_sec, scan.starts_ms)
                assert roll.series == scan.series and roll.total == scan.total
        assert r.users(f) == r.users(scan_of(f)) and len(r.users(f)) == 3
        only_auth = replace(f, cats=("auth",))
        assert r.users(only_auth) == r.users(scan_of(only_auth))
        assert r.histogram(f).total == len(r.page(f, None, MAX_PAGE).rows)
    finally:
        await idx.stop()


def test_histogram_shape(reader):
    h = reader.histogram(F(), buckets=6)
    assert h.start_ms == ms("2026-11-04T13:00:00+09:00") and h.to_ms == ms("2026-11-04T14:00:00+09:00")
    assert h.starts_ms == [h.start_ms + i * 600_000 for i in range(6)]
    off = reader.histogram(LogFilter(ms("2026-11-04T13:05:00+09:00"), ms("2026-11-04T14:00:00+09:00")), buckets=6)
    assert off.start_ms == ms("2026-11-04T13:00:00+09:00") and len(off.starts_ms) == 6
    assert off.series == [(None, [5, 10, 10, 0, 0, 0])] and off.source == "rollup"


def test_users_facet_scan_path_and_limit(reader):
    assert reader.users(F(q="cmd")) == [("a@x.com", 10), ("CORP\\hong", 10), ("CORP\\kim", 10)]
    assert reader.users(F(q="zebra", users=("a@x.com",))) == [("CORP\\kim", 1)]
    assert reader.users(F(), limit=1) == [("a@x.com", 10)]


def test_iter_rows_uses_its_own_connection_and_closes_it(reader, monkeypatch):
    opened: list[sqlite3.Connection] = []
    real = indexer_mod.open_reader

    def spy(path):
        conn = real(path); opened.append(conn); return conn

    monkeypatch.setattr(indexer_mod, "open_reader", spy)
    gen = reader.iter_rows(F(), limit=100, chunk=7)
    assert next(gen).data["text"] == "cmd-29" and len(opened) == 1
    gen.close()
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("SELECT 1")
    texts = [r.data["text"].split()[0] for r in reader.iter_rows(F(), limit=100, chunk=7)]
    assert texts == [f"cmd-{i}" for i in range(29, -1, -1)]
    with pytest.raises(sqlite3.ProgrammingError):
        opened[1].execute("SELECT 1")


def test_query_plans_avoid_a_sort(reader, tmp_path):
    """Every driving dimension reads its index in (ts_ms, id) order: no temp B-tree for ORDER BY."""
    cur = Cursor(ms("2026-11-04T13:20:00+09:00"), 21)
    filters = [F(), F(users=("CORP\\hong", "a@x.com")), F(cats=("activity.command", "auth")),
               F(users=("CORP\\hong",), cats=("activity.command",), session_id=2), F(client_ip="10.0.3.1"),
               F(cats=("auth",), outcomes=("fail",), events=("login",), channel="local"),
               F(users=("CORP\\kim",), q="zebra")]
    with closing(open_reader(tmp_path / "index.db")) as conn:
        for f in filters:
            for c in (None, cur):
                for sql, params in page_queries(f, c, 200):
                    plan = " | ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, params))
                    assert "TEMP B-TREE" not in plan and "USING INDEX" in plan, (f, plan)
        # the keyword alone drives through the FTS table (sorting its matches is the accepted cost)
        (sql, params), = page_queries(F(q="zebra"), None, 200)
        plan = " | ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, params))
        assert plan.index("events_fts") < plan.index("SEARCH e"), plan


def test_close_all_defers_closing_a_reader_in_use(tmp_path, reader, monkeypatch):
    """close_all() during a query on another thread: the query finishes, then its connection closes."""
    started, go = threading.Event(), threading.Event()
    opened: list[sqlite3.Connection] = []
    real = indexer_mod.open_reader

    def blocking_open(path):
        conn = real(path)
        opened.append(conn)
        if len(opened) == 1:
            def handler():
                started.set(); go.wait(5); return 0
            conn.set_progress_handler(handler, 1)
        return conn

    monkeypatch.setattr(indexer_mod, "open_reader", blocking_open)
    r = IndexReader(tmp_path / "index.db")
    result: dict[str, object] = {}

    def query():
        try:
            result["page"] = r.page(F(), None, 5)
        except Exception as exc:  # the failure being guarded against
            result["error"] = exc

    t = threading.Thread(target=query); t.start()
    try:
        assert started.wait(5)
        closer = threading.Thread(target=r.close_all); closer.start(); closer.join(2)
        assert not closer.is_alive(), "close_all blocked on a connection in use"
    finally:
        go.set()
        t.join(5)
    assert "error" not in result and len(result["page"].rows) == 5  # type: ignore[attr-defined]
    with pytest.raises(sqlite3.ProgrammingError):  # closed by its thread once the query released it
        opened[0].execute("SELECT 1")
    assert r.summary().rows == 30 and len(opened) == 2  # the next call opens a new connection
    r.close_all()
    with pytest.raises(sqlite3.ProgrammingError):
        opened[1].execute("SELECT 1")


# -- plan review I2: keyword + several values, the query time limit -----------------------------

def test_keyword_with_several_users_runs_the_match_once(reader):
    f = F(users=("CORP\\hong", "CORP\\kim", "a@x.com"), q="cmd")
    (sql, params), = page_queries(f, None, 200)  # one statement, not one per user
    assert sql.count("MATCH") == 1 and "events_fts CROSS JOIN" in sql
    rows = reader.page(f, None, 7).rows
    every = list(reader.page(F(q="cmd"), None, 100).rows)
    assert [r.id for r in rows] == [r.id for r in every][:7]
    # the user list is still a condition, and paging continues across it
    two = F(users=("CORP\\kim", "a@x.com"), q="cmd")
    p1 = reader.page(two, None, 5)
    p2 = reader.page(two, decode_cursor(p1.next_cursor), 100)
    got = p1.rows + p2.rows
    assert len(got) == 20 and {r.user.lower() for r in got} == {"corp\\kim", "a@x.com"}
    assert [r.ts_ms for r in got] == sorted((r.ts_ms for r in got), reverse=True)
    # one user (or several categories without a keyword) still reads its index in order
    assert len(page_queries(F(users=("CORP\\kim",), q="cmd"), None, 200)) == 1
    assert len(page_queries(F(cats=("auth", "activity.window")), None, 200)) == 2


def test_a_broad_keyword_pages_through_the_time_index(reader, tmp_path, monkeypatch):
    """A keyword matching many rows walks ix_events_ts newest first (no sort of every match); the
    rows are the same as through the FTS table."""
    from app.logstore import query as query_mod
    filters = [F(q="cmd"), F(users=("CORP\\kim", "a@x.com"), q="cmd"), F(cats=("auth", "activity.command"), q="cmd")]
    narrow = [[r.id for r in reader.page(f, None, 7).rows] for f in filters]
    with closing(open_reader(tmp_path / "index.db")) as conn:
        assert not query_mod.broad_keyword(conn, F(q="cmd").fts)
        monkeypatch.setattr(query_mod, "BROAD_KEYWORD_ROWS", 5)
        assert query_mod.broad_keyword(conn, F(q="cmd").fts) and not query_mod.broad_keyword(conn, F(q="zebra").fts)
        for f in filters:
            (sql, params), = page_queries(f, None, 200, broad=True)
            plan = " | ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, params))
            assert "ix_events_ts" in plan and "TEMP B-TREE" not in plan, plan
    assert [[r.id for r in reader.page(f, None, 7).rows] for f in filters] == narrow
    p1 = reader.page(filters[1], None, 5)
    rest = reader.page(filters[1], decode_cursor(p1.next_cursor), 100).rows
    assert len(p1.rows + rest) == 20


SPIN = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT COUNT(*) FROM c"


async def _spinning_index(tmp_path, clock, monkeypatch):
    """A LogIndex whose page() runs a statement that never ends unless interrupted."""
    from app.logstore import query as query_mod
    monkeypatch.setattr(query_mod, "page", lambda conn, f, cursor, limit: conn.execute(SPIN).fetchall())
    (tmp_path / "logs").mkdir()
    idx = LogIndex(tmp_path / "index.db", tmp_path / "logs", clock, ListLog())
    await idx.start(run_loop=False)
    return idx


async def test_a_query_past_its_time_limit_is_interrupted(tmp_path, clock, monkeypatch):
    import time as time_mod
    idx = await _spinning_index(tmp_path, clock, monkeypatch)
    try:
        idx.query_time_limit = 0.3
        t0 = time_mod.monotonic()
        with pytest.raises(indexer_mod.QueryTimeout):
            await idx.query(idx.reader().page, F(), None, 10)
        assert time_mod.monotonic() - t0 < 5 and not idx.query_slots.locked()
        # the reader's connection is still usable, without the handler
        assert idx.reader().summary().rows == 0
    finally:
        await idx.stop()


async def test_a_cancelled_query_frees_its_slot_promptly(tmp_path, clock, monkeypatch):
    import asyncio
    import time as time_mod
    idx = await _spinning_index(tmp_path, clock, monkeypatch)
    try:
        idx.query_time_limit = 60
        tasks = [asyncio.create_task(idx.query(idx.reader().page, F(), None, 10)) for _ in range(4)]
        await asyncio.sleep(0.3)
        assert idx.query_slots.locked()
        t0 = time_mod.monotonic()
        for t in tasks:
            t.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(r, asyncio.CancelledError) for r in results)
        assert time_mod.monotonic() - t0 < 5 and not idx.query_slots.locked()  # not 60 s
    finally:
        await idx.stop()


async def test_an_export_pull_runs_under_the_time_limit(tmp_path, clock, monkeypatch):
    idx = await _spinning_index(tmp_path, clock, monkeypatch)
    try:
        idx.query_time_limit = 0.3
        rows = idx.reader().iter_rows(F(), limit=10)
        with pytest.raises(indexer_mod.QueryTimeout):
            await idx.query(lambda: next(rows))
        rows.close()
    finally:
        await idx.stop()
