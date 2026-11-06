"""The log indexer: tails the daily JSONL files into ``data/index.db`` (rulings W2, W5, W10).

Writes go through :meth:`LogIndex.run_exclusive` only (one ``asyncio.Lock``, one writer connection,
used from a worker thread); reads go through :class:`IndexReader` (one read-only connection per
thread). Reading the files, parsing and normalizing all happen in the worker thread; the loop thread
only gets the counts back and writes the ``system`` ``logindex.*`` lines.
"""
from __future__ import annotations

import asyncio
import functools
import sqlite3
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO

from app.clock import KST, Clock
from app.logstore import query
from app.logstore.files import LogFile, list_log_files
from app.logstore.fts import InvalidQuery
from app.logstore.index_db import open_reader, prepare_index
from app.logstore.normalize import normalize
from app.logstore.query import Cursor, Histogram, LogFilter, LogRow, Page
from app.logstore.reader import open_log, parse_line, read_chunk
from app.logstore.writer import LogSink


@dataclass(frozen=True)
class FileState:
    """A row of the ``files`` table: how far a log file has been indexed."""

    name: str
    day: str
    offset: int
    size: int
    lines: int
    bad_lines: int
    done: bool


@dataclass(frozen=True)
class IndexStatus:
    ready: bool
    rebuilding: bool
    files: int
    pending_files: int
    pending_bytes: int
    rows: int
    bad_lines: int
    oldest_day: str | None
    newest_day: str | None
    last_indexed_at: datetime | None


@dataclass(frozen=True)
class IndexSummary:
    rows: int
    oldest_day: str | None
    newest_day: str | None


def _summary(conn: sqlite3.Connection) -> IndexSummary:
    # Three statements: MIN/MAX alone use the (day, line_hash) index; combined they would scan.
    rows = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    oldest = conn.execute("SELECT MIN(day) FROM events").fetchone()[0]
    newest = conn.execute("SELECT MAX(day) FROM events").fetchone()[0]
    return IndexSummary(int(rows), oldest, newest)


class _Slot:
    """A thread's reader connection and how many calls are using it right now."""

    __slots__ = ("conn", "busy", "retired")

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.busy = 0
        self.retired = False  # close_all() ran: closed when the last call using it ends


def _close_quietly(conn: sqlite3.Connection) -> None:
    try:
        conn.close()
    except sqlite3.Error:
        pass


class IndexReader:
    """Read-only access to the index: one connection per thread, all closable at once.

    Every method blocks; call them through ``asyncio.to_thread`` from the loop. ``close_all()`` closes
    the idle connections at once and a connection in use when its call ends, so a query running on
    another thread during a stop or rebuild finishes instead of failing.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._slots: list[_Slot] = []

    @contextmanager
    def _use(self) -> Iterator[sqlite3.Connection]:
        local = self._local
        slot: _Slot | None = getattr(local, "slot", None)
        with self._lock:  # check and mark in one step: close_all() cannot close it in between
            if slot is not None and not slot.retired:
                slot.busy += 1
            else:
                slot = None
        if slot is None:
            conn = open_reader(self._path)
            slot = _Slot(conn)
            slot.busy = 1
            with self._lock:
                self._slots.append(slot)
            local.slot = slot
        try:
            yield slot.conn
        finally:
            with self._lock:
                slot.busy -= 1
                close = slot.retired and slot.busy == 0
            if close:
                _close_quietly(slot.conn)

    def close_all(self) -> None:
        """Close every thread's connection (before the index file is deleted or rebuilt: Windows
        cannot delete a file that a connection of this process holds open). A connection in use is
        closed by its thread when the call ends. Threads open a new connection on their next call."""
        with self._lock:
            slots, self._slots = self._slots, []
            idle = []
            for slot in slots:
                slot.retired = True
                if slot.busy == 0:
                    idle.append(slot)
        for slot in idle:
            _close_quietly(slot.conn)

    def summary(self) -> IndexSummary:
        with self._use() as conn:
            return _summary(conn)

    def days(self) -> dict[str, int]:
        """Indexed rows per day."""
        with self._use() as conn:
            rows = conn.execute("SELECT day, COUNT(*) FROM events GROUP BY day").fetchall()
        return {day: int(n) for day, n in rows}

    def count_before_day(self, day: str) -> int:
        """Indexed rows of the days before ``day`` (``YYYY-MM-DD``)."""
        with self._use() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM events WHERE day < ?", (day,)).fetchone()[0])

    # -- queries (app.logstore.query) ---------------------------------------------------------------

    def page(self, f: LogFilter, cursor: Cursor | None, limit: int = query.DEFAULT_PAGE) -> Page:
        """Newest-first rows older than ``cursor``, at most ``limit`` (1..MAX_PAGE)."""
        if not 1 <= limit <= query.MAX_PAGE:
            raise InvalidQuery(f"limit must be 1-{query.MAX_PAGE}")
        with self._use() as conn:
            return query.page(conn, f, cursor, limit)

    def histogram(self, f: LogFilter, buckets: int = 60, group: query.Group = "none") -> Histogram:
        with self._use() as conn:
            return query.histogram(conn, f, buckets, group)

    def users(self, f: LogFilter, limit: int = 200) -> list[tuple[str, int]]:
        """Rows per user under ``f`` ignoring ``f.users``, most first."""
        with self._use() as conn:
            return query.users(conn, f, limit)

    def iter_rows(self, f: LogFilter, limit: int, chunk: int = 5000) -> Iterator[LogRow]:
        """Up to ``limit`` rows newest first, read ``chunk`` at a time through a connection of its
        own (an export may run long), closed when the rows end or the generator is closed."""
        if limit < 1 or chunk < 1:
            raise InvalidQuery("limit and chunk must be positive")
        return self._iter_rows(f, limit, chunk)

    def _iter_rows(self, f: LogFilter, limit: int, chunk: int) -> Iterator[LogRow]:
        conn = open_reader(self._path)
        try:
            cursor: Cursor | None = None
            left = limit
            while left > 0:
                p = query.page(conn, f, cursor, min(chunk, left))
                yield from p.rows
                left -= len(p.rows)
                if p.next_cursor is None:
                    return
                cursor = Cursor(p.rows[-1].ts_ms, p.rows[-1].id)
        finally:
            conn.close()


class _FileCursor:
    """Reads one log file batch by batch, keeping the handle open across batches (a ``.gz`` cannot
    seek without decompressing from the start). Used only inside ``run_exclusive`` calls."""

    def __init__(self, path: Path, offset: int, *, final: bool) -> None:
        self.path = path
        self.offset = offset  # where the first line not yet taken starts
        self.final = final
        self._fh: BinaryIO | None = None
        self._buf: list[tuple[int, bytes]] = []
        self._pos = 0
        self._next = offset  # where the read after the buffer starts
        self._eof = False

    @property
    def exhausted(self) -> bool:
        return self._eof and self._pos >= len(self._buf)

    def take(self, n: int) -> tuple[list[bytes], int]:
        """Up to ``n`` complete lines and how many oversized lines were skipped on the way."""
        if self._fh is None:
            self._fh = open_log(self.path)
        oversized = 0
        while self._pos >= len(self._buf) and not self._eof:
            chunk = read_chunk(self._fh, self._next, final=self.final)
            self._buf, self._pos, self._next, self._eof = chunk.lines, 0, chunk.next_offset, chunk.eof
            oversized += chunk.oversized
        end = min(self._pos + n, len(self._buf))
        lines = [raw for _, raw in self._buf[self._pos:end]]
        self._pos = end
        self.offset = self._buf[end][0] if end < len(self._buf) else self._next
        return lines, oversized

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


@dataclass(frozen=True)
class _Batch:
    inserted: int
    lines: int
    bad: int
    exhausted: bool
    offset: int


@dataclass(frozen=True)
class _FileResult:
    inserted: int
    lines: int
    finished: bool
    offset: int


_UPSERT_FILE = """
INSERT INTO files (name, day, "offset", size, lines, bad_lines, done) VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (name) DO UPDATE SET day = excluded.day, "offset" = excluded."offset", size = excluded.size,
    lines = lines + excluded.lines, bad_lines = bad_lines + excluded.bad_lines, done = excluded.done
"""
_INSERT_EVENT = """
INSERT OR IGNORE INTO events (ts_ms, day, cat, event, user, session_id, client_ip, outcome, line_hash, raw)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
_ROLLUP = """
INSERT INTO {table} (bucket, cat, user, n) VALUES (?, ?, ?, ?)
ON CONFLICT (bucket, cat, user) DO UPDATE SET n = n + excluded.n
"""


class LogIndex:
    """Keeps ``index.db`` up to date with the JSONL files in ``logs_dir``.

    Each cycle reads today's and yesterday's (KST) plain files to the end, then the files with work
    left newest day first, stopping after the batch that brings the backlog lines of the cycle to
    ``backlog_lines_per_cycle`` (W10; the recent files do not count against it).
    """

    def __init__(
        self,
        path: Path,
        logs_dir: Path,
        clock: Clock,
        log: LogSink,
        *,
        batch_lines: int = 5000,
        poll_sec: float = 1.0,
        backlog_lines_per_cycle: int = 50_000,
    ) -> None:
        self._path = Path(path)
        self._logs_dir = Path(logs_dir)
        self._clock = clock
        self._log = log
        self._batch_lines = batch_lines
        self._poll_sec = poll_sec
        self._backlog_budget = backlog_lines_per_cycle
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()  # run_exclusive: one writer at a time
        self._cycle_lock = asyncio.Lock()  # index_once: one cycle at a time
        self._inflight: asyncio.Future[object] | None = None
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._reader = IndexReader(self._path)
        self._status = IndexStatus(False, False, 0, 0, 0, 0, 0, None, None, None)
        self._eof_sizes: dict[str, int] = {}  # plain file → size it was last read to the end at
        self._stale = True  # the row and bad-line counts must be recomputed
        self._more = False  # the last cycle stopped on the backlog budget
        self._ready_logged = False
        self._started_at = 0.0
        self._last_error: str | None = None

    # -- lifecycle ---------------------------------------------------------------------------------

    async def start(self, run_loop: bool = True) -> None:
        """Open (or rebuild) the index; with ``run_loop``, index every ``poll_sec`` and on ``wake()``."""
        if self._conn is not None:
            return
        self._reader.close_all()  # a rebuild deletes the file: no reader may hold it open
        self._started_at = time.monotonic()
        conn, created, existed, files, states, summary, bad = await asyncio.to_thread(self._open)
        self._conn = conn
        if created and files:
            self._log.emit("system", event="logindex.rebuilt", reason="schema" if existed else "new")
        pending = [f for f in files if self._needs_work(f, states.get(f.name))]
        self._status = IndexStatus(
            ready=False,
            rebuilding=bool(files) and not states,
            files=len(files),
            pending_files=len(pending),
            pending_bytes=sum(self._pending_bytes(f, states.get(f.name)) for f in pending),
            rows=summary.rows,
            bad_lines=bad,
            oldest_day=summary.oldest_day,
            newest_day=summary.newest_day,
            last_indexed_at=None,
        )
        self._stale = False
        if run_loop:
            self._task = asyncio.create_task(self._run(), name="log-index")

    def _open(self) -> tuple[
        sqlite3.Connection, bool, bool, list[LogFile], dict[str, FileState], IndexSummary, int
    ]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        existed = self._path.is_file() and self._path.stat().st_size > 0
        conn, created = prepare_index(self._path)
        try:
            states = self._states(conn)
            summary = _summary(conn)
            bad = self._bad_lines(conn)
        except BaseException:
            conn.close()
            raise
        return conn, created, existed, list_log_files(self._logs_dir), states, summary, bad

    async def stop(self) -> None:
        """Stop the loop, wait for a batch in flight, close the readers and the writer connection."""
        task, self._task = self._task, None
        try:
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        finally:
            inflight = self._inflight
            if inflight is not None and not inflight.done():
                await asyncio.wait({inflight})  # a worker thread cannot be interrupted
            # Readers first: the writer, closing last, checkpoints and removes the -wal file.
            self._reader.close_all()
            conn, self._conn = self._conn, None
            if conn is not None:
                conn.close()

    def wake(self) -> None:
        """Index soon (loop thread; registered as a ``LogWriter`` flush listener)."""
        self._wake.set()

    def status(self) -> IndexStatus:
        """The result of the last cycle (loop thread)."""
        return self._status

    def reader(self) -> IndexReader:
        return self._reader

    async def run_exclusive[T](self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run ``fn(writer connection)`` in a worker thread, one call at a time.

        If the caller is cancelled, the lock is held until the thread is done (it cannot be
        interrupted), so nothing else uses or closes the connection meanwhile.
        """
        self._stale = True  # e.g. a retention purge: recount at the end of the next cycle
        return await self._exclusive(fn)

    async def _exclusive[T](self, fn: Callable[[sqlite3.Connection], T]) -> T:
        async with self._lock:
            conn = self._conn
            if conn is None:
                raise RuntimeError("the log index is not open")
            fut: asyncio.Future[T] = asyncio.ensure_future(asyncio.to_thread(fn, conn))
            self._inflight = fut  # type: ignore[assignment]
            try:
                return await asyncio.shield(fut)
            except asyncio.CancelledError:
                while not fut.done():
                    try:
                        await asyncio.wait({fut})
                    except asyncio.CancelledError:
                        continue
                if not fut.cancelled():
                    fut.exception()  # retrieved: the caller's cancellation wins
                raise

    async def _run(self) -> None:
        while True:
            self._wake.clear()
            try:
                await self.index_once()
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                if error != self._last_error:  # one line per distinct failure, not one per second
                    self._last_error = error
                    self._log.emit("system", event="logindex.cycle_failed", error=error)
                await asyncio.sleep(self._poll_sec)
                continue
            self._last_error = None
            if self._more:  # backlog left: go on at once (the recent files are read first again)
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(self._wake.wait(), self._poll_sec)
            except TimeoutError:
                pass

    # -- one cycle ---------------------------------------------------------------------------------

    async def index_once(self) -> int:
        """One indexing cycle; returns how many rows it inserted."""
        async with self._cycle_lock:
            return await self._cycle()

    def _needs_work(self, f: LogFile, state: FileState | None) -> bool:
        if f.compressed:
            return state is None or not state.done
        if self._eof_sizes.get(f.name) == f.size:
            return False  # read to the end at this size: only a partial last line is left
        return state is None or state.offset != f.size

    @staticmethod
    def _pending_bytes(f: LogFile, state: FileState | None) -> int:
        if f.compressed:
            return 0 if state is not None and state.done else f.size
        return max(0, f.size - (state.offset if state is not None else 0))

    async def _cycle(self) -> int:
        today = self._clock.now().astimezone(KST).date()
        recent = {today, today - timedelta(days=1)}
        files, states = await self._exclusive(self._load)
        names = {f.name for f in files}
        for name in [n for n in self._eof_sizes if n not in names]:
            del self._eof_sizes[name]
        work = [f for f in files if self._needs_work(f, states.get(f.name))]
        realtime = [f for f in work if not f.compressed and f.day in recent]
        backlog = sorted((f for f in work if f not in realtime), key=lambda f: f.day, reverse=True)

        inserted = 0
        finished: set[str] = set()
        offsets: dict[str, int] = {}
        for f in realtime:
            r = await self._index_file(f, states.get(f.name), None)
            inserted += r.inserted
            offsets[f.name] = r.offset
            if r.finished:
                finished.add(f.name)
        backlog_lines = 0
        for f in backlog:
            if backlog_lines >= self._backlog_budget:
                break
            r = await self._index_file(f, states.get(f.name), self._backlog_budget - backlog_lines)
            inserted += r.inserted
            backlog_lines += r.lines
            offsets[f.name] = r.offset
            if r.finished:
                finished.add(f.name)

        pending = [f for f in work if f.name not in finished]
        pending_bytes = 0
        for f in files:
            state = states.get(f.name)
            if f.name in finished and f.compressed:
                continue
            if f.name in offsets and not f.compressed:
                pending_bytes += max(0, f.size - offsets[f.name])
            else:
                pending_bytes += self._pending_bytes(f, state)
        self._more = bool(pending) and backlog_lines >= self._backlog_budget

        st = self._status
        if self._stale:
            self._stale = False
            summary, bad = await self._exclusive(lambda c: (_summary(c), self._bad_lines(c)))
            st = replace(st, rows=summary.rows, bad_lines=bad, oldest_day=summary.oldest_day,
                         newest_day=summary.newest_day)
        ready = not pending
        self._status = replace(
            st,
            ready=ready,
            rebuilding=st.rebuilding and not ready,
            files=len(files),
            pending_files=len(pending),
            pending_bytes=pending_bytes,
            last_indexed_at=self._clock.now(),
        )
        if ready and not self._ready_logged:
            self._ready_logged = True
            self._log.emit(
                "system", event="logindex.ready", rows=self._status.rows,
                duration_ms=round((time.monotonic() - self._started_at) * 1000),
            )
        return inserted

    @staticmethod
    def _states(conn: sqlite3.Connection) -> dict[str, FileState]:
        rows = conn.execute(
            'SELECT name, day, "offset", size, lines, bad_lines, done FROM files'
        ).fetchall()
        return {r[0]: FileState(r[0], r[1], r[2], r[3], r[4], r[5], bool(r[6])) for r in rows}

    @staticmethod
    def _bad_lines(conn: sqlite3.Connection) -> int:
        return int(conn.execute("SELECT COALESCE(SUM(bad_lines), 0) FROM files").fetchone()[0])

    def _load(self, conn: sqlite3.Connection) -> tuple[list[LogFile], dict[str, FileState]]:
        """The log files on disk and their states; states of files no longer on disk are dropped
        (their rows stay: retention removes rows by day)."""
        files = list_log_files(self._logs_dir)
        states = self._states(conn)
        gone = [(name,) for name in states if name not in {f.name for f in files}]
        if gone:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.executemany("DELETE FROM files WHERE name = ?", gone)
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            self._stale = True  # their bad-line counts went with them
            for (name,) in gone:
                del states[name]
        return files, states

    async def _index_file(self, f: LogFile, state: FileState | None, budget: int | None) -> _FileResult:
        """Index ``f`` batch by batch: to the end, or (``budget``) until that many lines were read."""
        offset = state.offset if state is not None else 0
        truncated: tuple[int, int] | None = None
        if not f.compressed and f.size < offset:
            truncated, offset = (offset, f.size), 0
        cursor = _FileCursor(f.path, offset, final=f.compressed)
        inserted = lines = bad = 0
        finished = False
        try:
            reset = truncated is not None
            while True:
                try:
                    batch = await self._exclusive(
                        functools.partial(self._index_batch, cursor=cursor, f=f, reset=reset)
                    )
                except FileNotFoundError:  # removed since the listing (retention): nothing to do
                    return _FileResult(inserted, lines, True, cursor.offset)
                if reset and truncated is not None:
                    reset = False
                    self._log.emit("system", event="logindex.file_truncated", file=f.name,
                                   before=truncated[0], after=truncated[1])
                inserted += batch.inserted
                lines += batch.lines
                bad += batch.bad
                if batch.exhausted:
                    finished = True
                    break
                if budget is not None and lines >= budget:
                    break
        finally:
            cursor.close()
            if bad:
                self._log.emit("system", event="logindex.bad_lines", file=f.name, count=bad)
        if finished and not f.compressed:
            self._eof_sizes[f.name] = f.size
        return _FileResult(inserted, lines, finished, cursor.offset)

    def _index_batch(self, conn: sqlite3.Connection, *, cursor: _FileCursor, f: LogFile, reset: bool) -> _Batch:
        """Worker thread: read up to ``batch_lines`` lines and index them in one transaction."""
        raws, oversized = cursor.take(self._batch_lines)
        day = f.day.isoformat()
        bad = oversized
        inserted = 0
        per_min: Counter[tuple[int, str, str]] = Counter()
        per_hour: Counter[tuple[int, str, str]] = Counter()
        conn.execute("BEGIN IMMEDIATE")
        try:
            for raw in raws:
                obj = parse_line(raw)
                if obj is None:
                    bad += 1
                    continue
                row = normalize(obj, raw, day)
                cur = conn.execute(_INSERT_EVENT, (
                    row.ts_ms, row.day, row.cat, row.event, row.user, row.session_id, row.client_ip,
                    row.outcome, row.line_hash, row.raw,
                ))
                if cur.rowcount != 1:  # the same line again (a retried batch, W5)
                    continue
                conn.execute("INSERT INTO events_fts (rowid, search) VALUES (?, ?)", (cur.lastrowid, row.search))
                user = row.user or ""
                per_min[(row.ts_ms // 60_000, row.cat, user)] += 1
                per_hour[(row.ts_ms // 3_600_000, row.cat, user)] += 1
                inserted += 1
            for table, counts in (("counts_min", per_min), ("counts_hour", per_hour)):
                if counts:
                    conn.executemany(_ROLLUP.format(table=table), [(*k, n) for k, n in counts.items()])
            if reset:
                conn.execute("UPDATE files SET lines = 0, bad_lines = 0 WHERE name = ?", (f.name,))
            exhausted = cursor.exhausted
            conn.execute(_UPSERT_FILE, (
                f.name, day, cursor.offset, f.size, len(raws), bad,
                int(f.compressed and exhausted),
            ))
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        if inserted or bad or reset:
            self._stale = True
        return _Batch(inserted, len(raws), bad, exhausted, cursor.offset)
