"""Log retention: the read-only preview (Plan 3) and the daily clean-up job (rulings W14–W16).

The job deletes exactly what the preview showed (the same :func:`retention_cutoff`): the log files of
the days before the cutoff, their index rows, and the expired rows of the ``config.db`` tables. It
also gzips old plain files that are fully indexed. File work happens in worker threads through
``LogIndex.run_exclusive`` (the indexer is not reading meanwhile, F23); ``config.db`` work happens on
the loop thread, one short transaction per table.
"""
from __future__ import annotations

import asyncio
import functools
import gzip
import hashlib
import os
import sqlite3
import time as _time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from app.auth.otp import OTP_EMAIL_FAIL_WINDOW_SEC, OTP_IP_WINDOW_SEC, OTP_VERIFY_IP_WINDOW_SEC
from app.auth.sessions import SESSION_ABSOLUTE_SEC, SESSION_IDLE_SEC
from app.clock import KST, Clock, to_kst_iso
from app.logstore.files import LogFile, list_log_files
from app.logstore.indexer import LogIndex, rename_file_state

if TYPE_CHECKING:
    from app.activity.tamper import TamperScanner
    from app.audit import AuditLogger
    from app.db import Database
    from app.logstore.writer import LogWriter
    from app.paths import AppPaths
    from app.settings.store import SettingsStore


def retention_cutoff(today: date, days: int) -> date:
    """The oldest date kept: ``days`` dates including ``today``. Files dated before it are deletable."""
    return today - timedelta(days=days - 1)


@dataclass(frozen=True)
class RetentionPreview:
    days: int
    cutoff: date
    total_files: int
    total_bytes: int
    oldest_date: date | None
    delete_files: int
    delete_bytes: int
    delete_from: date | None
    delete_to: date | None


def preview(logs_dir: Path, today: date, days: int) -> RetentionPreview:
    cutoff = retention_cutoff(today, days)
    files = [(f.day, f.size) for f in list_log_files(Path(logs_dir))]
    doomed = [(d, size) for d, size in files if d < cutoff]
    return RetentionPreview(
        days=days,
        cutoff=cutoff,
        total_files=len(files),
        total_bytes=sum(size for _, size in files),
        oldest_date=min((d for d, _ in files), default=None),
        delete_files=len(doomed),
        delete_bytes=sum(size for _, size in doomed),
        delete_from=min((d for d, _ in doomed), default=None),
        delete_to=max((d for d, _ in doomed), default=None),
    )


# -- the daily job ---------------------------------------------------------------------------------

RUN_AT_KST = time(3, 30)
MIN_COMPRESS_AGE_DAYS = 2
LOG_DB_TABLES = ("mcp_actions", "mcp_transitions", "notice_displays", "rdp_connections", "rdp_logon_failures")
DB_TABLES = ("auth_sessions", "otp_codes", "otp_failures", "otp_verify_ip", "otp_ip_requests", *LOG_DB_TABLES)
OTP_CODE_KEEP_SEC = 3600
STOP_GRACE_SEC = 10.0
_MAX_SLEEP_SEC = 600.0  # the schedule re-reads the clock at least this often
_LAST_RUN_KEY = "retention_last_run"

Reason = Literal["schedule", "startup", "settings", "manual"]


def compress_cutoff(today: date, compress_after_days: int) -> date:
    """Plain files dated before this are gzipped: never yesterday's or today's (W15)."""
    return retention_cutoff(today, max(compress_after_days, MIN_COMPRESS_AGE_DAYS))


@dataclass(frozen=True)
class RetentionResult:
    reason: str
    cutoff: date
    compress_cutoff: date
    deleted_files: list[str]
    deleted_bytes: int
    deleted_from: date | None
    deleted_to: date | None
    index_rows: int
    compressed: list[str]
    skipped_compress: list[str]
    db_rows: dict[str, int]
    errors: list[str]
    duration_ms: int


def _unlink_each(_conn: sqlite3.Connection, paths: list[Path]) -> list[OSError | None]:
    """Worker thread (inside ``run_exclusive``): delete each file; its error or None."""
    out: list[OSError | None] = []
    for p in paths:
        try:
            p.unlink(missing_ok=True)
        except OSError as exc:  # e.g. WinError 32: another program has it open
            out.append(exc)
        else:
            out.append(None)
    return out


def _line_key(line: bytes) -> bytes:
    return hashlib.blake2b(line[:-1] if line.endswith(b"\n") else line, digest_size=16).digest()


def _write_gz(plain: Path, limit: int, gz: Path | None, tmp: Path, inner_name: str) -> int:
    """Worker thread: write ``tmp`` = the lines of ``gz`` (when given) followed by the first ``limit``
    bytes of ``plain``, gzipped (level 6, mtime 0) and fsynced. Lines already in ``gz`` are not
    added again (the index treats them as one line too), so merging twice is harmless. Returns the
    uncompressed size."""
    total = 0
    try:
        with open(tmp, "wb") as raw:
            with gzip.GzipFile(filename=inner_name, fileobj=raw, mode="wb", compresslevel=6, mtime=0) as out:
                seen: set[bytes] | None = None
                if gz is not None:
                    seen = set()
                    last = b"\n"
                    with gzip.open(gz, "rb") as old:
                        for line in old:
                            out.write(line)
                            total += len(line)
                            seen.add(_line_key(line))
                            last = line[-1:]
                    if last != b"\n":
                        out.write(b"\n")
                        total += 1
                with open(plain, "rb") as src:
                    left = limit
                    if seen is None:
                        while left > 0 and (chunk := src.read(min(left, 1 << 20))):
                            out.write(chunk)
                            total += len(chunk)
                            left -= len(chunk)
                    else:
                        for line in src:
                            if left <= 0:
                                break
                            line = line[:left]
                            left -= len(line)
                            if _line_key(line) not in seen:
                                out.write(line)
                                total += len(line)
            raw.flush()
            os.fsync(raw.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return total


def _swap_in(conn: sqlite3.Connection, *, plain: Path, size: int, tmp: Path, gz: Path, offset: int) -> bool:
    """Worker thread (inside ``run_exclusive``): put ``tmp`` in place of ``gz``, delete ``plain`` and
    move its index state onto ``gz``. False (nothing changed) when ``plain`` grew since it was read.
    If ``plain`` cannot be deleted the error is raised; the next run merges it again harmlessly."""
    if plain.stat().st_size != size:  # a late line was appended: leave it for the next run
        tmp.unlink(missing_ok=True)
        return False
    os.replace(tmp, gz)
    plain.unlink()
    rename_file_state(conn, plain.parent, plain.name, gz.name, offset)
    return True


def _read_last_run(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (_LAST_RUN_KEY,)).fetchone()
    return row[0] if row is not None else None


def _write_last_run(conn: sqlite3.Connection, day: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (_LAST_RUN_KEY, day),
    )


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return (dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)).astimezone(UTC)


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


class RetentionJob:
    """Runs the clean-up every day at ``run_at`` KST, once ``startup_delay_sec`` after a start that
    missed today's run, and ``request_delay_sec`` after a confirmed retention change (W14).

    ``run_once`` never overlaps itself. ``stop()`` cancels what is only waiting and lets a run in
    progress finish (at most ``stop_grace_sec``, then it is cancelled too; F14).
    """

    def __init__(
        self,
        paths: AppPaths,
        db: Database,
        settings: SettingsStore,
        index: LogIndex,
        log: LogWriter,
        audit: AuditLogger,
        clock: Clock,
        tamper_scanner: TamperScanner | None,
        *,
        run_at: time = RUN_AT_KST,
        startup_delay_sec: float = 60,
        request_delay_sec: float = 5,
        delete_chunk: int = 5000,
        stop_grace_sec: float = STOP_GRACE_SEC,
    ) -> None:
        self._paths = paths
        self._db = db
        self._settings = settings
        self._index = index
        self._log = log
        self._audit = audit
        self._clock = clock
        self._scanner = tamper_scanner
        self._run_at = run_at
        self._startup_delay = startup_delay_sec
        self.request_delay_sec = request_delay_sec
        self._delete_chunk = delete_chunk
        self._stop_grace = stop_grace_sec
        self._lock = asyncio.Lock()
        self._run_task: asyncio.Task[object] | None = None  # the task inside run_once
        self._tasks: set[asyncio.Task[None]] = set()  # the schedule loop and requested runs
        self._queued = False  # a requested run is still waiting for its delay
        self._started = False
        self._stopped = False

    # -- scheduling ------------------------------------------------------------------------------

    def next_run_at(self, now: datetime) -> datetime:
        """The first ``run_at`` KST strictly after ``now`` (UTC-aware)."""
        local = now.astimezone(KST)
        at = datetime.combine(local.date(), self._run_at, KST)
        if at <= local:
            at += timedelta(days=1)
        return at.astimezone(UTC)

    def _spawn(self, coro: Coroutine[object, object, None], name: str) -> None:
        task = asyncio.get_running_loop().create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def request_run(self, reason: Reason = "settings") -> None:
        """Run ``request_delay_sec`` from now unless a requested run is already waiting (loop thread)."""
        if self._stopped or self._queued:
            return
        self._queued = True
        self._spawn(self._requested(reason), "retention-request")

    async def _requested(self, reason: Reason) -> None:
        try:
            await asyncio.sleep(self.request_delay_sec)
        finally:
            self._queued = False
        await self._guarded(reason)

    async def start(self) -> None:
        """Start the schedule; a start after today's ``run_at`` that finds no run today also runs
        once ``startup_delay_sec`` later."""
        if self._started or self._stopped:
            return
        self._started = True
        now = self._clock.now()
        today = now.astimezone(KST).date()
        try:
            last = await self._index.run_exclusive(_read_last_run)
        except Exception:  # the index cannot be read: assume today has not run
            last = None
        missed = last != today.isoformat() and now >= datetime.combine(today, self._run_at, KST)
        self._spawn(self._schedule(missed), "retention-schedule")

    async def _schedule(self, missed: bool) -> None:
        if missed:
            await asyncio.sleep(self._startup_delay)
            await self._guarded("startup")
        while not self._stopped:
            target = self.next_run_at(self._clock.now())
            while (left := (target - self._clock.now()).total_seconds()) > 0:
                await asyncio.sleep(min(left, _MAX_SLEEP_SEC))
            await self._guarded("schedule")

    async def _guarded(self, reason: Reason) -> None:
        try:
            await self.run_once(reason)
        except Exception as exc:
            self._log.emit("system", event="retention.failed", error=f"{type(exc).__name__}: {exc}")

    async def stop(self) -> None:
        """Cancel the waiting tasks; let a run in progress finish (bounded), then cancel the rest."""
        self._stopped = True
        tasks = list(self._tasks)
        for task in tasks:
            if task is not self._run_task:
                task.cancel()
        if not tasks:
            return
        _, late = await asyncio.wait(tasks, timeout=self._stop_grace)
        for task in late:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # -- one run ---------------------------------------------------------------------------------

    async def run_once(self, reason: Reason) -> RetentionResult:
        async with self._lock:
            self._run_task = asyncio.current_task()
            try:
                return await self._run(reason)
            finally:
                self._run_task = None

    async def _run(self, reason: Reason) -> RetentionResult:
        started = _time.monotonic()
        s = self._settings.get()
        now = self._clock.now()
        today = now.astimezone(KST).date()
        cutoff = retention_cutoff(today, s.log_retention_days)
        cc = compress_cutoff(today, s.log_compress_after_days)
        errors: list[str] = []

        deleted: list[LogFile] = []
        try:
            deleted = await self._delete_files(cutoff, errors)
        except Exception as exc:
            errors.append(f"files: {exc!r}")
        index_rows = 0
        try:
            index_rows = await self._index.delete_before(cutoff.isoformat(), self._delete_chunk)
        except Exception as exc:
            errors.append(f"index: {exc!r}")
        compressed: list[str] = []
        skipped: list[str] = []
        try:
            await self._compress(cutoff, cc, compressed, skipped, errors)
        except Exception as exc:
            errors.append(f"compress: {exc!r}")
        db_rows = self._purge_db(now, cutoff, errors)
        try:
            await self._index.run_exclusive(functools.partial(_write_last_run, day=today.isoformat()))
        except Exception as exc:
            errors.append(f"meta: {exc!r}")

        result = RetentionResult(
            reason=reason,
            cutoff=cutoff,
            compress_cutoff=cc,
            deleted_files=[f.name for f in deleted],
            deleted_bytes=sum(f.size for f in deleted),
            deleted_from=min((f.day for f in deleted), default=None),
            deleted_to=max((f.day for f in deleted), default=None),
            index_rows=index_rows,
            compressed=compressed,
            skipped_compress=skipped,
            db_rows=db_rows,
            errors=errors,
            duration_ms=round((_time.monotonic() - started) * 1000),
        )
        self._report(result)
        return result

    def _report(self, r: RetentionResult) -> None:
        self._log.emit(
            "system", event="retention.run", reason=r.reason, cutoff=r.cutoff.isoformat(),
            compress_cutoff=r.compress_cutoff.isoformat(), deleted_files=len(r.deleted_files),
            deleted_bytes=r.deleted_bytes, deleted_from=_iso(r.deleted_from), deleted_to=_iso(r.deleted_to),
            index_rows=r.index_rows, compressed=len(r.compressed), skipped_compress=len(r.skipped_compress),
            db_rows=r.db_rows, errors=r.errors, duration_ms=r.duration_ms,
        )
        if r.deleted_files or r.index_rows or any(r.db_rows[t] for t in LOG_DB_TABLES):
            self._audit.admin(
                None, "retention_purge", "local", None,
                {
                    "reason": r.reason, "cutoff": r.cutoff.isoformat(), "deleted_from": _iso(r.deleted_from),
                    "deleted_to": _iso(r.deleted_to), "files": len(r.deleted_files), "bytes": r.deleted_bytes,
                    "index_rows": r.index_rows, "db_rows": r.db_rows,
                },
                "error" if r.errors else "ok",
            )

    async def _delete_files(self, cutoff: date, errors: list[str]) -> list[LogFile]:
        """Delete every log file (plain and gz) dated before ``cutoff``; the ones deleted."""
        doomed = [f for f in await asyncio.to_thread(list_log_files, self._paths.logs_dir) if f.day < cutoff]
        if not doomed:
            return []
        for f in doomed:  # announced first: a scan may run while the files go
            self._expect_removed(f.name)
        try:
            results = await self._index.run_exclusive(
                functools.partial(_unlink_each, paths=[f.path for f in doomed])
            )
        except BaseException:
            for f in doomed:
                if f.path.exists():
                    self._cancel_removal(f.name)
            raise
        deleted: list[LogFile] = []
        for f, err in zip(doomed, results, strict=True):
            if err is None:
                deleted.append(f)
            else:
                self._cancel_removal(f.name)
                errors.append(f"files: {f.name}: {err!r}")
        return deleted

    async def _compress(
        self, cutoff: date, cc: date, compressed: list[str], skipped: list[str], errors: list[str]
    ) -> None:
        files = await asyncio.to_thread(list_log_files, self._paths.logs_dir)
        gz_by_name = {f.name: f for f in files if f.compressed}
        # an expired file still here could not be deleted: the next run deletes it, not gzips it
        old = (f for f in files if not f.compressed and cutoff <= f.day < cc)
        for f in sorted(old, key=lambda f: f.name):
            try:
                done = await self._compress_one(f, gz_by_name.get(f.name + ".gz"))
            except Exception as exc:
                errors.append(f"compress: {f.name}: {exc!r}")
                continue
            (compressed if done else skipped).append(f.name)

    async def _compress_one(self, f: LogFile, gz: LogFile | None) -> bool:
        """Gzip the plain file ``f`` (merged into ``gz`` when one exists for the day). False when it
        is not fully indexed yet (W15), or the day's ``gz`` is not, or ``f`` grew meanwhile."""
        state = await self._index.file_state(f.name)
        if state is None or state.offset != f.size:
            return False
        if gz is not None:
            gz_state = await self._index.file_state(gz.name)
            if gz_state is None or not gz_state.done:
                return False
        gz_path = f.path.with_name(f.name + ".gz")
        tmp = f.path.with_name(f.name + ".gz.tmp")
        offset = await asyncio.to_thread(
            _write_gz, f.path, state.offset, gz.path if gz is not None else None, tmp, f.name
        )
        self._expect_removed(f.name)
        try:
            done = await self._index.run_exclusive(functools.partial(
                _swap_in, plain=f.path, size=state.offset, tmp=tmp, gz=gz_path, offset=offset
            ))
        except BaseException:
            self._cancel_removal(f.name)
            tmp.unlink(missing_ok=True)
            raise
        if not done:
            self._cancel_removal(f.name)
        return done

    def _expect_removed(self, name: str) -> None:
        if self._scanner is not None:
            self._scanner.expect_log_removed(name)

    def _cancel_removal(self, name: str) -> None:
        if self._scanner is not None:
            self._scanner.cancel_log_removal(name)

    # -- config.db -------------------------------------------------------------------------------

    def _purge_db(self, now: datetime, cutoff: date, errors: list[str]) -> dict[str, int]:
        """Delete the expired rows, one short transaction per table (loop thread, W16)."""
        kst_before = {sec: to_kst_iso(now - timedelta(seconds=sec)) for sec in (
            OTP_CODE_KEEP_SEC, OTP_EMAIL_FAIL_WINDOW_SEC, OTP_VERIFY_IP_WINDOW_SEC, OTP_IP_WINDOW_SEC)}
        # UTC isoformat() strings sort like the times they hold (same prefix order), so < is safe.
        cut = datetime.combine(cutoff, time(0), KST).astimezone(UTC).isoformat()
        ended = "ended_at IS NOT NULL AND ended_at < ?"

        def sql(statement: str, *params: object) -> Callable[[sqlite3.Connection], int]:
            return lambda conn: conn.execute(statement, params).rowcount

        steps: list[tuple[str, Callable[[sqlite3.Connection], int]]] = [
            ("auth_sessions", functools.partial(self._purge_sessions, now=now)),
            ("otp_codes", sql(
                "DELETE FROM otp_codes WHERE last_sent_at < ?"
                " AND (code_hash IS NULL OR email NOT IN (SELECT email FROM users))",
                kst_before[OTP_CODE_KEEP_SEC])),
            ("otp_failures", sql("DELETE FROM otp_failures WHERE at < ?", kst_before[OTP_EMAIL_FAIL_WINDOW_SEC])),
            ("otp_verify_ip", sql("DELETE FROM otp_verify_ip WHERE at < ?", kst_before[OTP_VERIFY_IP_WINDOW_SEC])),
            ("otp_ip_requests", sql("DELETE FROM otp_ip_requests WHERE at < ?", kst_before[OTP_IP_WINDOW_SEC])),
            ("mcp_actions", sql("DELETE FROM mcp_actions WHERE at < ?", cut)),
            ("mcp_transitions", sql("DELETE FROM mcp_transitions WHERE at < ?", cut)),
            # before the connections: the FK cascade would delete these rows uncounted
            ("notice_displays", sql(
                f"DELETE FROM notice_displays WHERE connection_id IN (SELECT id FROM rdp_connections WHERE {ended})",
                cut)),
            ("rdp_connections", sql(f"DELETE FROM rdp_connections WHERE {ended}", cut)),
            ("rdp_logon_failures", sql("DELETE FROM rdp_logon_failures WHERE at < ?", cut)),
        ]
        rows = dict.fromkeys(DB_TABLES, 0)
        for table, step in steps:
            try:
                with self._db.transaction() as conn:
                    rows[table] = step(conn)
            except Exception as exc:
                errors.append(f"db: {table}: {exc!r}")
        return rows

    @staticmethod
    def _purge_sessions(conn: sqlite3.Connection, now: datetime) -> int:
        """Login sessions past the absolute or idle limit (the same rule as ``SessionStore.get``);
        the timestamps are parsed because some have microseconds and some do not."""
        expired: list[tuple[str]] = []
        for r in conn.execute("SELECT id_hash, created_at, last_seen_at FROM auth_sessions").fetchall():
            try:
                created, seen = _parse_utc(r[1]), _parse_utc(r[2])
            except ValueError:  # not ours: left alone
                continue
            if ((now - created).total_seconds() >= SESSION_ABSOLUTE_SEC
                    or (now - seen).total_seconds() >= SESSION_IDLE_SEC):
                expired.append((r[0],))
        conn.executemany("DELETE FROM auth_sessions WHERE id_hash = ?", expired)
        return len(expired)
