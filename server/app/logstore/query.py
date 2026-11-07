"""Log queries over ``data/index.db``: keyset pages, histograms and user facets (rulings W7, W8).

Every function here takes a read-only connection and blocks; :class:`app.logstore.indexer.IndexReader`
exposes them as methods (one connection per thread). All SQL uses bound parameters only.

Pages are newest first with a ``(ts_ms, id)`` keyset cursor. A filter with several users or
categories is read value by value through that column's ``(value, ts_ms)`` index, already in order,
and the results are merged (``heapq.merge``): no temporary B-tree for the ``ORDER BY`` (W7). With a
keyword as well, one statement serves all of them (the MATCH runs once): driven by the keyword's
matches when they are few, by the time index when they are many (``broad_keyword``).
Histograms and user counts come from the minute/hour rollups when the filter only has time,
category and user conditions on minute boundaries, otherwise from counting rows (W8).
"""
from __future__ import annotations

import base64
import heapq
import itertools
import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.logstore.fts import InvalidQuery, fts_expression
from app.logstore.normalize import CATEGORIES, OUTCOMES

DEFAULT_PAGE = 200
MAX_PAGE = 1000
MAX_USERS = 50
MAX_EVENTS = 20
MAX_SPAN_MS = 3660 * 86_400_000
BUCKET_LADDER_SEC = (60, 300, 600, 1800, 3600, 10800, 21600, 43200, 86400)
KST_OFFSET_MS = 9 * 3_600_000
TOP_USERS = 10
BROAD_KEYWORD_ROWS = 20_000  # a keyword matching this many rows pages through the time index

OTHER_USERS = "__other__"  # the histogram series of the users outside the top TOP_USERS
CHANNELS = ("local", "external")
MAX_USER_CHARS = 256
MAX_EVENT_CHARS = 64
MAX_CURSOR_CHARS = 400

Group = Literal["none", "cat", "user"]

_MIN_MS = 60_000
_HOUR_MS = 3_600_000
_INT64_MIN, _INT64_MAX = -(2**63), 2**63 - 1
_ASCII_FOLD = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _fold(user: str) -> str:
    """The key SQLite's NOCASE collation compares (ASCII letters only)."""
    return user.translate(_ASCII_FOLD)


@dataclass(frozen=True)
class LogFilter:
    """The conditions of a log query; the time range is ``[from_ms, to_ms)`` (UTC epoch ms)."""

    from_ms: int
    to_ms: int
    users: tuple[str, ...] = ()
    cats: tuple[str, ...] = ()
    events: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ()
    session_id: int | None = None
    client_ip: str | None = None
    q: str | None = None
    channel: str | None = None
    fts: str | None = field(init=False, default=None, repr=False, compare=False)  # MATCH of ``q``

    def __post_init__(self) -> None:
        if not self.from_ms < self.to_ms:
            raise InvalidQuery("from must be before to")
        if self.to_ms - self.from_ms > MAX_SPAN_MS:
            raise InvalidQuery("the time range is too long")
        if len(self.users) > MAX_USERS or any(not 1 <= len(u) <= MAX_USER_CHARS for u in self.users):
            raise InvalidQuery(f"at most {MAX_USERS} users of 1-{MAX_USER_CHARS} characters")
        if any(c not in CATEGORIES for c in self.cats):
            raise InvalidQuery("unknown category")
        if len(self.events) > MAX_EVENTS or any(not 1 <= len(e) <= MAX_EVENT_CHARS for e in self.events):
            raise InvalidQuery(f"at most {MAX_EVENTS} events of 1-{MAX_EVENT_CHARS} characters")
        if any(o not in OUTCOMES for o in self.outcomes):
            raise InvalidQuery("unknown outcome")
        if self.session_id is not None and not _INT64_MIN <= self.session_id <= _INT64_MAX:
            raise InvalidQuery("session id out of range")
        if self.channel is not None and self.channel not in CHANNELS:
            raise InvalidQuery("unknown channel")
        object.__setattr__(self, "fts", fts_expression(self.q))


@dataclass(frozen=True)
class Cursor:
    ts_ms: int
    id: int


def encode_cursor(c: Cursor) -> str:
    """``[ts_ms, id]`` as JSON in unpadded base64url."""
    raw = json.dumps([c.ts_ms, c.id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(s: str) -> Cursor:
    """The cursor ``encode_cursor`` made; ``InvalidQuery`` for anything else."""
    if not s or len(s) > MAX_CURSOR_CHARS:
        raise InvalidQuery("bad cursor")
    try:
        value = json.loads(base64.b64decode(s + "=" * (-len(s) % 4), altchars=b"-_", validate=True))
    except ValueError:  # binascii.Error, non-ASCII text, bad UTF-8 and bad JSON are all ValueErrors
        raise InvalidQuery("bad cursor") from None
    if not (isinstance(value, list) and len(value) == 2
            and all(type(v) is int and _INT64_MIN <= v <= _INT64_MAX for v in value)):
        raise InvalidQuery("bad cursor")
    return Cursor(value[0], value[1])


@dataclass(frozen=True)
class LogRow:
    id: int
    ts_ms: int
    cat: str
    event: str | None
    user: str | None
    session_id: int | None
    client_ip: str | None
    outcome: str | None
    data: dict[str, Any]
    raw: str = field(default="", repr=False, compare=False)  # the line as written (JSONL export)


@dataclass(frozen=True)
class Page:
    rows: list[LogRow]
    next_cursor: str | None


@dataclass(frozen=True)
class Histogram:
    start_ms: int
    to_ms: int
    bucket_sec: int
    starts_ms: list[int]
    series: list[tuple[str | None, list[int]]]
    total: int
    source: Literal["rollup", "scan"]


def choose_bucket(span_ms: int, max_buckets: int) -> int:
    """The smallest ladder bucket (seconds) giving at most ``max_buckets`` bars, else whole days."""
    for b in BUCKET_LADDER_SEC:
        if -(-span_ms // (b * 1000)) <= max_buckets:
            return b
    return 86400 * -(-span_ms // (86_400_000 * max_buckets))


def bucket_start(from_ms: int, bucket_sec: int) -> int:
    """The start of the bucket holding ``from_ms``, buckets aligned to KST midnight (W8)."""
    b_ms = bucket_sec * 1000
    return ((from_ms + KST_OFFSET_MS) // b_ms) * b_ms - KST_OFFSET_MS


# -- conditions ------------------------------------------------------------------------------------

_COLUMNS = "e.id, e.ts_ms, e.cat, e.event, e.user, e.session_id, e.client_ip, e.outcome, e.raw"
_FTS_FROM = "events_fts CROSS JOIN events AS e ON e.id = events_fts.rowid"  # the keyword drives
_FTS_IN = "e.id IN (SELECT rowid FROM events_fts WHERE events_fts MATCH ?)"


@dataclass(frozen=True)
class _Driver:
    """The dimension a page query reads through: an index on ``(column, ts_ms)``, ``ix_events_ts``
    alone, or the FTS table."""

    kind: Literal["session", "ip", "user", "cat", "fts", "time"]
    values: tuple[Any, ...] = (None,)

    @property
    def column(self) -> str:
        return {"session": "e.session_id", "ip": "e.client_ip", "user": "e.user", "cat": "e.cat"}[self.kind]

    @property
    def index(self) -> str:
        return {"session": "ix_events_session", "ip": "ix_events_ip", "user": "ix_events_user",
                "cat": "ix_events_cat", "time": "ix_events_ts"}[self.kind]


def _unique(values: Iterable[str], key: Any = None) -> tuple[str, ...]:
    seen: dict[str, str] = {}
    for v in values:
        seen.setdefault(key(v) if key else v, v)
    return tuple(seen.values())


def _driver(f: LogFilter, *, users: bool = True) -> _Driver:
    """Session → IP → users → categories → (keyword alone) → time (W7)."""
    if f.session_id is not None:
        return _Driver("session", (f.session_id,))
    if f.client_ip is not None:
        return _Driver("ip", (f.client_ip,))
    if users and f.users:
        return _Driver("user", _unique(f.users, _fold))  # one query per user, NOCASE
    if f.cats:
        return _Driver("cat", _unique(f.cats))
    if f.fts is not None:
        return _Driver("fts")
    return _Driver("time")


def _residual(f: LogFilter, driver: _Driver, *, users: bool = True) -> tuple[list[str], list[Any]]:
    """The conditions besides time and the driving column."""
    where: list[str] = []
    params: list[Any] = []

    def is_in(column: str, values: Sequence[Any]) -> None:
        where.append(f"{column} IN ({', '.join('?' * len(values))})")
        params.extend(values)

    if f.session_id is not None and driver.kind != "session":
        where.append("e.session_id = ?"); params.append(f.session_id)
    if f.client_ip is not None and driver.kind != "ip":
        where.append("e.client_ip = ?"); params.append(f.client_ip)
    if users and f.users and driver.kind != "user":
        is_in("e.user", f.users)
    if f.cats and driver.kind != "cat":
        is_in("e.cat", f.cats)
    if f.events:
        is_in("e.event", f.events)
    if f.outcomes:
        is_in("e.outcome", f.outcomes)
    if f.channel is not None:
        where.append("json_extract(e.raw, '$.channel') = ?"); params.append(f.channel)
    if f.fts is not None and driver.kind != "fts":
        where.append(_FTS_IN); params.append(f.fts)
    return where, params


# -- pages -----------------------------------------------------------------------------------------

def _keyword_drives(f: LogFilter) -> bool:
    """The keyword decides the page's plan: alone, or with several users or categories (one
    statement for all of them: per value, each statement would evaluate the MATCH again, so 25
    users x a common word took seconds, plan review I2)."""
    if f.fts is None:
        return False
    driver = _driver(f)
    return driver.kind == "fts" or len(driver.values) > 1


def broad_keyword(conn: sqlite3.Connection, fts: str) -> bool:
    """Whether the keyword matches at least ``BROAD_KEYWORD_ROWS`` rows, counted only up to that cap
    (a few ms even for a one-letter prefix)."""
    sql = "SELECT COUNT(*) FROM (SELECT rowid FROM events_fts WHERE events_fts MATCH ? LIMIT ?)"
    return int(conn.execute(sql, (fts, BROAD_KEYWORD_ROWS)).fetchone()[0]) >= BROAD_KEYWORD_ROWS


def page_queries(
    f: LogFilter, cursor: Cursor | None, limit: int, *, broad: bool = False
) -> list[tuple[str, list[Any]]]:
    """The SQL of one page: a query per driving value, each ``LIMIT limit + 1``, newest first.

    When the keyword drives (:func:`_keyword_drives`): a narrow keyword drives one statement through
    its matches (sorting them is cheap); a ``broad`` one (:func:`broad_keyword`) walks the time index
    newest first with the matches as a set built once, and stops at the page: sorting hundreds of
    thousands of matches is what made a common word slow (W9, plan review I2)."""
    driver = _driver(f)
    if _keyword_drives(f):
        driver = _Driver("time") if broad else _Driver("fts")
    hi = f.to_ms if cursor is None else min(f.to_ms, cursor.ts_ms + 1)
    queries: list[tuple[str, list[Any]]] = []
    for value in driver.values:
        where = ["e.ts_ms >= ?", "e.ts_ms < ?"]
        params: list[Any] = [f.from_ms, hi]
        if cursor is not None:  # (ts_ms, id) < cursor, given ts_ms <= cursor.ts_ms
            where.append("NOT (e.ts_ms = ? AND e.id >= ?)"); params += [cursor.ts_ms, cursor.id]
        if driver.kind == "fts":
            source = _FTS_FROM
            where.insert(0, "events_fts MATCH ?"); params.insert(0, f.fts)
        else:
            source = f"events AS e INDEXED BY {driver.index}"
            if driver.kind != "time":
                where.insert(0, f"{driver.column} = ?"); params.insert(0, value)
        rest, rest_params = _residual(f, driver)
        sql = (f"SELECT {_COLUMNS} FROM {source} WHERE {' AND '.join(where + rest)} "
               "ORDER BY e.ts_ms DESC, e.id DESC LIMIT ?")
        queries.append((sql, params + rest_params + [limit + 1]))
    return queries


def _log_row(r: Sequence[Any]) -> LogRow:
    return LogRow(id=r[0], ts_ms=r[1], cat=r[2], event=r[3], user=r[4], session_id=r[5], client_ip=r[6],
                  outcome=r[7], data=json.loads(r[8]), raw=r[8])


def page(conn: sqlite3.Connection, f: LogFilter, cursor: Cursor | None, limit: int) -> Page:
    """Up to ``limit`` rows older than ``cursor`` (newest first) and the cursor of the next page."""
    broad = _keyword_drives(f) and broad_keyword(conn, f.fts or "")
    results = [conn.execute(sql, params).fetchall() for sql, params in page_queries(f, cursor, limit, broad=broad)]
    if len(results) == 1:
        raw = results[0]
    else:
        merged = heapq.merge(*results, key=lambda r: (-r[1], -r[0]))
        raw = list(itertools.islice(merged, limit + 1))
    rows = [_log_row(r) for r in raw[:limit]]
    next_cursor = encode_cursor(Cursor(rows[-1].ts_ms, rows[-1].id)) if len(raw) > limit else None
    return Page(rows, next_cursor)


# -- counts ----------------------------------------------------------------------------------------

def _rollup_ok(f: LogFilter) -> bool:
    """Only time, category and user conditions, on minute boundaries: the rollups count exactly."""
    return (f.fts is None and f.session_id is None and f.client_ip is None and not f.events
            and not f.outcomes and f.channel is None
            and f.from_ms % _MIN_MS == 0 and f.to_ms % _MIN_MS == 0)


def _rollup_ranges(from_ms: int, to_ms: int, hours: bool) -> list[tuple[str, int, int, int]]:
    """``(table, unit_ms, first bucket, end bucket)`` covering ``[from_ms, to_ms)``: whole hours
    from ``counts_hour`` when ``hours``, the minutes around them from ``counts_min``."""
    h1 = -(-from_ms // _HOUR_MS) * _HOUR_MS
    h2 = to_ms // _HOUR_MS * _HOUR_MS
    if not hours or h1 >= h2:
        return [("counts_min", _MIN_MS, from_ms // _MIN_MS, to_ms // _MIN_MS)]
    ranges = [("counts_hour", _HOUR_MS, h1 // _HOUR_MS, h2 // _HOUR_MS)]
    if from_ms < h1:
        ranges.append(("counts_min", _MIN_MS, from_ms // _MIN_MS, h1 // _MIN_MS))
    if h2 < to_ms:
        ranges.append(("counts_min", _MIN_MS, h2 // _MIN_MS, to_ms // _MIN_MS))
    return ranges


# A count row: (bar index, category or user or None, count).
_Count = tuple[int, str | None, int]


def _rollup_counts(conn: sqlite3.Connection, f: LogFilter, bars: tuple[int, int] | None, group: Group,
                   *, hours: bool, users: bool = True) -> list[_Count]:
    """Counts from the rollups; ``bars = (start_ms, bar_ms)`` splits them into bars, None sums the
    whole range (bar index 0)."""
    out: list[_Count] = []
    key, display = {"none": ("NULL", "NULL"), "cat": ("cat", "cat"),
                    "user": ("user", "MIN(user COLLATE BINARY)")}[group]
    for table, unit, lo, hi in _rollup_ranges(f.from_ms, f.to_ms, hours):
        where = ["bucket >= ?", "bucket < ?"]
        params: list[Any] = [lo, hi]
        if bars is None:
            k_sql = "0"
            group_by = key
        else:
            k_sql = "(bucket * ? - ?) / ?"
            params[:0] = [unit, bars[0], bars[1]]
            group_by = "k" if group == "none" else f"k, {key}"
        if f.cats:
            where.append(f"cat IN ({', '.join('?' * len(f.cats))})"); params += f.cats
        if users and f.users:
            where.append(f"user IN ({', '.join('?' * len(f.users))})"); params += f.users
        sql = (f"SELECT {k_sql} AS k, {display}, SUM(n) FROM {table} "
               f"WHERE {' AND '.join(where)} GROUP BY {group_by}")
        out += conn.execute(sql, params).fetchall()
    return out


def _scan_counts(conn: sqlite3.Connection, f: LogFilter, bars: tuple[int, int] | None, group: Group,
                 *, users: bool = True) -> list[_Count]:
    """Counts from the rows (same conditions as a page); ``bars`` as in :func:`_rollup_counts`."""
    driver = _driver(f, users=users)
    where = ["e.ts_ms >= ?", "e.ts_ms < ?"]
    params: list[Any] = [f.from_ms, f.to_ms]
    if driver.kind == "fts":
        source = _FTS_FROM
        where.insert(0, "events_fts MATCH ?"); params.insert(0, f.fts)
    else:  # one statement; IN lists let SQLite pick the index (no order to keep)
        source = "events AS e"
        driver = _Driver("time")
    rest, rest_params = _residual(f, driver, users=users)
    key, display = {"none": ("NULL", "NULL"), "cat": ("e.cat", "e.cat"),
                    "user": ("e.user", "MIN(e.user COLLATE BINARY)")}[group]
    k_params: list[Any] = []
    if bars is None:
        k_sql, group_by = "0", key
    else:
        k_sql, k_params = "(e.ts_ms - ?) / ?", [bars[0], bars[1]]
        group_by = "k" if group == "none" else f"k, {key}"
    sql = (f"SELECT {k_sql} AS k, {display}, COUNT(*) FROM {source} "
           f"WHERE {' AND '.join(where + rest)} GROUP BY {group_by}")
    return conn.execute(sql, k_params + params + rest_params).fetchall()


def _by_user(counts: Iterable[_Count]) -> tuple[dict[str, int], dict[str, str], int]:
    """Totals per NOCASE user key, a display name per key (the binary-smallest spelling) and the
    total of rows without a user."""
    totals: dict[str, int] = {}
    names: dict[str, str] = {}
    nobody = 0
    for _k, name, n in counts:
        if not name:
            nobody += n
            continue
        key = _fold(name)
        totals[key] = totals.get(key, 0) + n
        names[key] = min(names.get(key, name), name)
    return totals, names, nobody


def histogram(conn: sqlite3.Connection, f: LogFilter, buckets: int = 60, group: Group = "none") -> Histogram:
    """Row counts in KST-aligned bars of a ladder size, at most about ``buckets`` bars (W8)."""
    if buckets < 1:
        raise InvalidQuery("buckets must be positive")
    if group not in ("none", "cat", "user"):
        raise InvalidQuery("unknown group")
    b = choose_bucket(f.to_ms - f.from_ms, buckets)
    b_ms = b * 1000
    start = bucket_start(f.from_ms, b)
    n = -(-(f.to_ms - start) // b_ms)
    source: Literal["rollup", "scan"]
    if _rollup_ok(f):
        # Bars of an hour or more start on whole hours (KST is UTC+9), so hour rows fit them.
        counts, source = _rollup_counts(conn, f, (start, b_ms), group, hours=b >= 3600), "rollup"
    else:
        counts, source = _scan_counts(conn, f, (start, b_ms), group), "scan"

    series: list[tuple[str | None, list[int]]]
    if group == "none":
        bars = [0] * n
        for k, _key, c in counts:
            bars[k] += c
        series = [(None, bars)]
    elif group == "cat":
        per_cat: dict[str, list[int]] = {}
        for k, cat, c in counts:
            per_cat.setdefault(str(cat), [0] * n)[k] += c
        series = [(cat, per_cat[cat]) for cat in CATEGORIES if cat in per_cat]
    else:
        totals, names, nobody = _by_user(counts)
        top = sorted(totals, key=lambda u: (-totals[u], names[u].lower()))[:TOP_USERS]
        rows: dict[str | None, list[int]] = {names[u]: [0] * n for u in top}
        other = [0] * n
        none = [0] * n
        for k, name, c in counts:
            if not name:
                none[k] += c
            elif _fold(name) in top:
                rows[names[_fold(name)]][k] += c
            else:
                other[k] += c
        series = list(rows.items())
        if sum(other):
            series.append((OTHER_USERS, other))
        if nobody:
            series.append((None, none))
    return Histogram(
        start_ms=start, to_ms=f.to_ms, bucket_sec=b, starts_ms=[start + i * b_ms for i in range(n)],
        series=series, total=sum(c for _k, _key, c in counts), source=source,
    )


def users(conn: sqlite3.Connection, f: LogFilter, limit: int = 200) -> list[tuple[str, int]]:
    """Rows per user under ``f`` without its user condition (empty users left out), most first."""
    if limit < 1:
        raise InvalidQuery("limit must be positive")
    if _rollup_ok(f):
        counts = _rollup_counts(conn, f, None, "user", hours=True, users=False)
    else:
        counts = _scan_counts(conn, f, None, "user", users=False)
    totals, names, _nobody = _by_user(counts)
    ranked = sorted(totals, key=lambda u: (-totals[u], names[u].lower()))[:limit]
    return [(names[u], totals[u]) for u in ranked]
