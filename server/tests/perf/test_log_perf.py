import statistics
import time
from contextlib import closing

import pytest

from app.logstore.index_db import open_reader
from app.logstore.indexer import QUERY_TIME_LIMIT_SEC
from app.logstore.query import Histogram, Page, page_queries
from tests.perf.conftest import (
    ALL_USERS,
    BROAD_WITH_USERS,
    DAY15_NOON_MS,
    S2_USERS,
    SCENARIOS,
    cache_dir,
    deep_cursor,
    last_days,
    record,
)

# The first test builds the 1M-row cache (minutes) inside its setup: a long timeout here only (F03).
pytestmark = [pytest.mark.perf, pytest.mark.timeout(1800)]


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_query_under_300ms(perf_index, name):
    run = SCENARIOS[name]
    run(perf_index)  # warm-up
    times = []
    for _ in range(5):
        t = time.perf_counter(); run(perf_index); times.append(time.perf_counter() - t)
    med = statistics.median(times)
    record(name, med)
    print(f"{name}: median {med * 1000:.1f} ms")
    assert med < 0.300, f"{name}: median {med * 1000:.0f} ms"


@pytest.mark.parametrize("name", list(BROAD_WITH_USERS))
def test_broad_keyword_with_every_user_is_bounded(perf_index, name):
    """Plan review I2: a broad keyword (W9 excludes it from the 300 ms criterion) with all 25 users
    costs about what the keyword alone costs, far under the per-query time limit; recorded only."""
    run = BROAD_WITH_USERS[name]
    run(perf_index)
    times = []
    for _ in range(3):
        t = time.perf_counter(); run(perf_index); times.append(time.perf_counter() - t)
    med = statistics.median(times)
    record(name, med)
    print(f"{name}: median {med * 1000:.1f} ms")
    assert med < QUERY_TIME_LIMIT_SEC / 4, f"{name}: median {med * 1000:.0f} ms"


def test_keyword_with_users_scenarios_hit_rows(perf_index):
    p = perf_index
    s11 = SCENARIOS["S11"](p)
    assert isinstance(s11, Page) and len(s11.rows) == 200 and all("zebra-" in r.data["text"] for r in s11.rows)
    s12 = SCENARIOS["S12"](p)
    assert isinstance(s12, Page) and len(s12.rows) == 200 and len({r.user for r in s12.rows}) > 1
    s13 = SCENARIOS["S13"](p)
    assert isinstance(s13, Histogram) and s13.total == SCENARIOS["S9"](p).total  # every user = no user filter
    (sql, _params), = page_queries(last_days(30, users=ALL_USERS, q="zebra"), None, 200)
    assert sql.count("MATCH") == 1  # one statement for all 25 users


def test_ingest_rate(perf_index):
    record("ingest_lines_per_sec", perf_index.ingest_rate)
    assert perf_index.ingest_rate >= 2000


def test_scenarios_return_what_they_measure(perf_index):
    """The scenarios hit real rows on the path they are named for."""
    p = perf_index
    s1 = SCENARIOS["S1"](p)
    assert isinstance(s1, Page) and len(s1.rows) == 200 and s1.next_cursor
    s2 = SCENARIOS["S2"](p)
    assert isinstance(s2, Page) and {r.user for r in s2.rows} == set(S2_USERS)
    s4 = SCENARIOS["S4"](p)
    assert isinstance(s4, Page) and len(s4.rows) == 200 and all("zebra-" in r.data["text"] for r in s4.rows)
    s5 = SCENARIOS["S5"](p)
    assert isinstance(s5, Page) and s5.rows and {(r.user, r.cat) for r in s5.rows} == {("CORP\\user05", "activity.window")}
    for name, source in (("S6", "rollup"), ("S7", "rollup"), ("S9", "scan")):
        h = SCENARIOS[name](p)
        assert isinstance(h, Histogram) and h.source == source and h.total > 0, name
    s6 = SCENARIOS["S6"](p)
    assert isinstance(s6, Histogram) and s6.total == p.info.rows and len(s6.starts_ms) == 60
    s9 = SCENARIOS["S9"](p)
    assert isinstance(s9, Histogram) and 0.003 * p.info.rows < s9.total < 0.007 * p.info.rows  # about 0.5%
    users = SCENARIOS["S8"](p)
    assert isinstance(users, list) and len(users) == 25 and sum(n for _u, n in users) < p.info.rows
    cursor = deep_cursor(p)
    s10 = SCENARIOS["S10"](p)
    assert isinstance(s10, Page) and len(s10.rows) == 200 and cursor.ts_ms < DAY15_NOON_MS
    assert all((r.ts_ms, r.id) < (cursor.ts_ms, cursor.id) for r in s10.rows)


def test_page_plans_use_no_sort(perf_index):
    """EXPLAIN QUERY PLAN at 1M rows: S1–S3, S5 and S10 read their index in order (no temp B-tree)."""
    filters = {
        "S1": (last_days(1), None),
        "S2": (last_days(7, users=S2_USERS), None),
        "S3": (last_days(30, cats=("activity.command",)), None),
        "S5": (last_days(7, users=("CORP\\user05",), cats=("activity.window",),
                         session_id=perf_index.info.sessions["CORP\\user05"]), None),
        "S10": (last_days(30), deep_cursor(perf_index)),
    }
    with closing(open_reader(cache_dir() / "index.db")) as conn:
        for name, (f, cursor) in filters.items():
            for sql, params in page_queries(f, cursor, 200):
                plan = " | ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, params))
                print(f"{name}: {plan}")
                assert "TEMP B-TREE" not in plan, (name, plan)
