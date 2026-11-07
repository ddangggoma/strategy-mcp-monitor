"""The 1M-row performance harness (ruling W9): a cached index and the S1–S10 scenarios.

The index is built once under ``server/.cache/perf-v{GEN_VERSION}-1000000/`` (gitignored, W39) and
reused; ``meta.json`` is written last, so an interrupted build starts over. Building takes minutes:
run ``python -m tests.perf.gen`` first, or let the first perf test build it (the perf modules carry a
long ``timeout`` mark, F03).
"""
from __future__ import annotations

import asyncio
import json
import shutil
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pytest
import pytest_asyncio

from app.audit import AuditLogger
from app.clock import KST
from app.db import Database
from app.logstore.indexer import IndexReader, LogIndex
from app.logstore.query import Cursor, LogFilter
from app.logstore.retention import RetentionJob
from app.paths import AppPaths
from app.settings.store import SettingsStore
from tests.fakes import FakeClock
from tests.perf.gen import GEN_VERSION, WEB_USERS, WINDOWS_USERS, GenInfo, generate
from tests.winfakes import ListLog

CACHE_ROOT = Path(__file__).resolve().parents[2] / ".cache"
RESULTS = CACHE_ROOT / "perf-results.json"
PERF_ROWS = 1_000_000
PERF_DAYS = 30
PERF_END_DAY = date(2026, 11, 4)
PERF_SEED = 20261108
DAY_MS = 86_400_000
END_MS = int(datetime(2026, 11, 5, tzinfo=KST).timestamp() * 1000)  # 2026-11-05 00:00 KST


@dataclass(frozen=True)
class PerfIndex:
    reader: IndexReader
    info: GenInfo
    ingest_rate: float


def cache_dir(rows: int = PERF_ROWS) -> Path:
    return CACHE_ROOT / f"perf-v{GEN_VERSION}-{rows}"


async def _index(path: Path, logs: Path) -> None:
    clock = FakeClock(datetime(2026, 11, 5, tzinfo=KST))
    idx = LogIndex(path, logs, clock, ListLog(), backlog_lines_per_cycle=200_000)
    await idx.start(run_loop=False)
    try:
        while not idx.status().ready:
            await idx.index_once()
    finally:
        await idx.stop()


def ensure_cache(rows: int = PERF_ROWS) -> dict:
    """Generate and index ``rows`` rows unless the cache already holds them; the cache's meta."""
    d = cache_dir(rows)
    meta_path = d / "meta.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("gen_version") == GEN_VERSION and meta.get("rows") == rows:
            return meta
    if d.exists():
        shutil.rmtree(d)
    t0 = time.perf_counter()
    info = generate(d / "logs", rows, PERF_DAYS, PERF_END_DAY, PERF_SEED)
    gen_sec = time.perf_counter() - t0
    t0 = time.perf_counter()
    asyncio.run(_index(d / "index.db", d / "logs"))
    ingest_sec = time.perf_counter() - t0
    reader = IndexReader(d / "index.db")
    try:
        indexed = reader.summary().rows
    finally:
        reader.close_all()
    if indexed != rows:
        raise RuntimeError(f"the perf index holds {indexed} rows, expected {rows}")
    meta = {
        "gen_version": GEN_VERSION, "rows": rows, "days": info.days, "end_day": info.end_day.isoformat(),
        "users": info.users, "sessions": info.sessions, "gen_sec": round(gen_sec, 1),
        "ingest_sec": round(ingest_sec, 1), "ingest_rate": rows / ingest_sec,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def record(name: str, value: float) -> None:
    """Store a measurement (seconds or a count) under ``name`` in ``server/.cache/perf-results.json``."""
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    data = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.is_file() else {}
    data[name] = value
    RESULTS.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


@pytest.fixture(scope="session")
def perf_index() -> Iterator[PerfIndex]:
    meta = ensure_cache()
    info = GenInfo(rows=meta["rows"], days=meta["days"], users=meta["users"], sessions=meta["sessions"],
                   end_day=date.fromisoformat(meta["end_day"]))
    reader = IndexReader(cache_dir() / "index.db")
    yield PerfIndex(reader=reader, info=info, ingest_rate=meta["ingest_rate"])
    reader.close_all()


def last_days(days: int, **kw: object) -> LogFilter:
    """The ``days`` days before ``end`` (2026-11-05 00:00 KST)."""
    return LogFilter(from_ms=END_MS - days * DAY_MS, to_ms=END_MS, **kw)  # type: ignore[arg-type]


S2_USERS = ("CORP\\user03", "CORP\\user11")
ALL_USERS = (*WINDOWS_USERS, *WEB_USERS)  # all 25
DAY15_NOON_MS = END_MS - 30 * DAY_MS + 14 * DAY_MS + 12 * 3_600_000  # 2026-10-20 12:00 KST
_deep: dict[int, Cursor] = {}


def deep_cursor(p: PerfIndex) -> Cursor:
    """The newest row before noon of day 15 of the 30 days: S10 pages on from the middle of the data."""
    if id(p) not in _deep:
        row = p.reader.page(LogFilter(END_MS - 30 * DAY_MS, DAY15_NOON_MS), None, 1).rows[0]
        _deep[id(p)] = Cursor(row.ts_ms, row.id)
    return _deep[id(p)]


SCENARIOS: dict[str, Callable[[PerfIndex], object]] = {
    "S1": lambda p: p.reader.page(last_days(1), None),
    "S2": lambda p: p.reader.page(last_days(7, users=S2_USERS), None),
    "S3": lambda p: p.reader.page(last_days(30, cats=("activity.command",)), None),
    "S4": lambda p: p.reader.page(last_days(30, q="zebra"), None),
    "S5": lambda p: p.reader.page(last_days(7, users=("CORP\\user05",), cats=("activity.window",),
                                            session_id=p.info.sessions["CORP\\user05"]), None),
    "S6": lambda p: p.reader.histogram(last_days(30), 60, "cat"),
    "S7": lambda p: p.reader.histogram(last_days(7, users=S2_USERS), 60, "none"),
    "S8": lambda p: p.reader.users(last_days(30)),
    "S9": lambda p: p.reader.histogram(last_days(30, q="zebra"), 60),
    "S10": lambda p: p.reader.page(last_days(30), deep_cursor(p)),
    # plan review I2: a keyword with every user selected (the MATCH runs once, not once per user)
    "S11": lambda p: p.reader.page(last_days(30, users=ALL_USERS, q="zebra"), None),
    "S12": lambda p: p.reader.page(last_days(30, users=ALL_USERS, q="chrome"), None),
    "S13": lambda p: p.reader.histogram(last_days(30, users=ALL_USERS, q="zebra"), 60),
}

# Broad keywords (W9: over 300 ms even alone) with every user: measured and bounded, not held to 300 ms.
BROAD_WITH_USERS: dict[str, Callable[[PerfIndex], object]] = {
    "B1 focus x25 page": lambda p: p.reader.page(last_days(30, users=ALL_USERS, q="focus"), None),
    "B2 focus x25 histogram": lambda p: p.reader.histogram(last_days(30, users=ALL_USERS, q="focus"), 60),
    "B3 chrome x25 histogram": lambda p: p.reader.histogram(last_days(30, users=ALL_USERS, q="chrome"), 60),
    "B4 t x25 + category page": lambda p: p.reader.page(
        last_days(30, users=ALL_USERS, cats=("activity.window",), q="t"), None),
}


# -- the retention purge (Task 6) ------------------------------------------------------------------

PURGE_ROWS = 200_000
PURGE_DAYS = 10
PURGE_END_DAY = date(2026, 11, 4)


@dataclass(frozen=True)
class PurgeEnv:
    job: RetentionJob
    reader: IndexReader
    recent_filter: LogFilter


def purge_cache_dir() -> Path:
    return CACHE_ROOT / f"perf-purge-v{GEN_VERSION}"


def ensure_purge_cache() -> Path:
    """The 200,000-row / 10-day template (logs + index), built once; ``meta.json`` is written last."""
    d = purge_cache_dir()
    if (d / "meta.json").is_file():
        return d
    if d.exists():
        shutil.rmtree(d)
    generate(d / "logs", PURGE_ROWS, PURGE_DAYS, PURGE_END_DAY, PERF_SEED)
    asyncio.run(_index(d / "index.db", d / "logs"))
    (d / "meta.json").write_text(json.dumps({"gen_version": GEN_VERSION, "rows": PURGE_ROWS}), encoding="utf-8")
    return d


@pytest_asyncio.fixture
async def perf_purge(tmp_path) -> AsyncIterator[PurgeEnv]:
    """A copy of the template under ``tmp_path`` and a job keeping 7 days (compress after 7) on
    2026-11-06, two days after the data ends (F04): it deletes 10-26..10-30, 100,000 rows."""
    src = await asyncio.to_thread(ensure_purge_cache)
    paths = AppPaths(tmp_path)
    paths.ensure()
    await asyncio.to_thread(shutil.copytree, src / "logs", paths.logs_dir, dirs_exist_ok=True)
    await asyncio.to_thread(shutil.copy2, src / "index.db", paths.index_db_path)
    clock = FakeClock(datetime(2026, 11, 6, 12, tzinfo=KST))
    db = Database(paths.db_path)
    db.migrate()
    settings = SettingsStore(db)
    settings.update({"log_retention_days": 7, "log_compress_after_days": 7})
    log = ListLog()
    index = LogIndex(paths.index_db_path, paths.logs_dir, clock, log)
    await index.start(run_loop=False)
    job = RetentionJob(paths, db, settings, index, log, AuditLogger(log), clock, None)
    try:
        yield PurgeEnv(job, index.reader(), LogFilter(END_MS - DAY_MS, END_MS))  # the newest 24 h of the data
    finally:
        await job.stop()
        await index.stop()
        db.close()
