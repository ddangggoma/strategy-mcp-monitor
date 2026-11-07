from __future__ import annotations

import sqlite3
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.clock import Clock
from app.db import Database
from app.monitor.models import ActionKind, Issue, McpState, Trigger
from app.monitor.runner import ScriptResult

SPARKLINE_POINTS = 60
HISTORY_KEEP_DAYS = 7

_MINUTE_FORMAT = "%Y-%m-%dT%H:%MZ"


def minute_key(at: datetime) -> str:
    """UTC minute bucket key, ``YYYY-MM-DDTHH:MMZ`` (sorts lexicographically by time)."""
    return at.astimezone(UTC).strftime(_MINUTE_FORMAT)


def _parse_minute(key: str) -> datetime:
    return datetime.strptime(key, _MINUTE_FORMAT).replace(tzinfo=UTC)


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _db_dt(at: datetime) -> str:
    return at.astimezone(UTC).isoformat()


@dataclass(frozen=True)
class MinuteBucket:
    minute: datetime
    ok: int
    total: int
    avg_latency_ms: float | None
    max_latency_ms: float | None


@dataclass(frozen=True)
class ActionRecord:
    run_id: str
    mcp_id: int
    at: datetime
    requested: ActionKind
    kind: ActionKind
    trigger: Trigger
    reason: str
    actor_id: int | None
    result: ScriptResult
    id: int | None = None


@dataclass(frozen=True)
class TransitionRecord:
    at: datetime
    from_state: McpState
    to_state: McpState
    issue: Issue | None


class _Acc:
    """Counters of one (mcp, minute) bucket."""

    __slots__ = ("ok", "total", "latency_sum", "latency_n", "latency_max")

    def __init__(self) -> None:
        self.ok = 0
        self.total = 0
        self.latency_sum = 0.0
        self.latency_n = 0
        self.latency_max: float | None = None

    def add(self, other: _Acc) -> None:
        self.ok += other.ok
        self.total += other.total
        self.latency_sum += other.latency_sum
        self.latency_n += other.latency_n
        if other.latency_max is not None and (
            self.latency_max is None or other.latency_max > self.latency_max
        ):
            self.latency_max = other.latency_max


class _Live:
    """In-memory state of one MCP: sparkline, last check and unflushed buckets."""

    def __init__(self) -> None:
        self.sparkline: deque[float | None] = deque(maxlen=SPARKLINE_POINTS)
        self.last_check_at: datetime | None = None
        self.pending: dict[str, _Acc] = {}


# Additive upsert. SQLite's scalar max() returns NULL if either side is NULL, so the
# latency_max merge is spelled out: a NULL never overwrites a value.
# The SELECT ... FROM mcps makes a write for an MCP deleted meanwhile a silent no-op.
_UPSERT = """
INSERT INTO mcp_minutes (mcp_id, minute, ok, total, latency_sum, latency_n, latency_max)
SELECT id, ?, ?, ?, ?, ?, ? FROM mcps WHERE id = ?
ON CONFLICT (mcp_id, minute) DO UPDATE SET
    ok = ok + excluded.ok,
    total = total + excluded.total,
    latency_sum = latency_sum + excluded.latency_sum,
    latency_n = latency_n + excluded.latency_n,
    latency_max = CASE
        WHEN latency_max IS NULL THEN excluded.latency_max
        WHEN excluded.latency_max IS NULL THEN latency_max
        ELSE max(latency_max, excluded.latency_max)
    END
"""


class McpHistory:
    """Check history of MCPs. Call from the event-loop thread only.

    ``record`` touches memory only, except that a minute rollover writes the finished
    minutes to ``mcp_minutes``. Unflushed buckets are merged into every read, so reads
    are always complete.
    """

    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock
        self._live: dict[int, _Live] = {}
        # (mcp_id, hours) -> (window start key, stored ok, stored total); see ``uptime``.
        self._uptime_db: dict[tuple[int, int], tuple[str, int, int]] = {}

    # ---- checks / uptime ----

    def record(
        self,
        mcp_id: int,
        at: datetime,
        ok: bool,
        latency_ms: float | None,
        counted: bool = True,
    ) -> None:
        live = self._live.get(mcp_id)
        if live is None:
            live = self._live[mcp_id] = _Live()
        live.sparkline.append(latency_ms if ok else None)
        live.last_check_at = at
        if not counted:
            return
        key = minute_key(at)
        finished = {k: a for k, a in live.pending.items() if k < key}
        if finished:
            self._write(mcp_id, finished)
            for k in finished:
                del live.pending[k]
        acc = live.pending.get(key)
        if acc is None:
            acc = live.pending[key] = _Acc()
        acc.total += 1
        if ok:
            acc.ok += 1
            if latency_ms is not None:
                acc.latency_sum += latency_ms
                acc.latency_n += 1
                if acc.latency_max is None or latency_ms > acc.latency_max:
                    acc.latency_max = latency_ms

    def sparkline(self, mcp_id: int) -> list[float | None]:
        live = self._live.get(mcp_id)
        return list(live.sparkline) if live else []

    def last_check_at(self, mcp_id: int) -> datetime | None:
        live = self._live.get(mcp_id)
        return live.last_check_at if live else None

    def uptime(self, mcp_id: int, hours: int = 24) -> float | None:
        """Share of ok checks since ``hours`` ago (minute granularity), None without checks.

        The stored part (a SUM over up to 1,440 rows) is cached per MCP for the current minute
        bucket: it changes only when the window start moves (minute rollover) or rows are written
        (rollover writes, ``flush``) or purged; ``invalidate`` drops it explicitly. Unflushed
        counts are added live on every call.
        """
        since = minute_key(self._clock.now() - timedelta(hours=hours))
        cached = self._uptime_db.get((mcp_id, hours))
        if cached is not None and cached[0] == since:
            ok, total = cached[1], cached[2]
        else:
            row = self._db.query(
                "SELECT SUM(ok) AS ok, SUM(total) AS total FROM mcp_minutes"
                " WHERE mcp_id = ? AND minute >= ?",
                (mcp_id, since),
            )[0]
            ok, total = row["ok"] or 0, row["total"] or 0
            self._uptime_db[(mcp_id, hours)] = (since, ok, total)
        live = self._live.get(mcp_id)
        if live:
            for key, acc in live.pending.items():
                if key >= since:
                    ok += acc.ok
                    total += acc.total
        return ok / total if total else None

    def buckets(self, mcp_id: int, since: datetime) -> list[MinuteBucket]:
        """Per-minute buckets from ``since`` (minute granularity), oldest first.

        Includes unflushed buckets; a minute present in both places is summed.
        """
        since_key = minute_key(since)
        merged: dict[str, _Acc] = {}
        for row in self._db.query(
            "SELECT minute, ok, total, latency_sum, latency_n, latency_max FROM mcp_minutes"
            " WHERE mcp_id = ? AND minute >= ?",
            (mcp_id, since_key),
        ):
            acc = merged[row["minute"]] = _Acc()
            acc.ok, acc.total = row["ok"], row["total"]
            acc.latency_sum, acc.latency_n = row["latency_sum"], row["latency_n"]
            acc.latency_max = row["latency_max"]
        live = self._live.get(mcp_id)
        if live:
            for key, pend in live.pending.items():
                if key >= since_key:
                    merged.setdefault(key, _Acc()).add(pend)
        return [
            MinuteBucket(
                minute=_parse_minute(key),
                ok=acc.ok,
                total=acc.total,
                avg_latency_ms=acc.latency_sum / acc.latency_n if acc.latency_n else None,
                max_latency_ms=acc.latency_max,
            )
            for key, acc in sorted(merged.items())
        ]

    def invalidate(self, mcp_id: int) -> None:
        """Drop the cached stored uptime of ``mcp_id`` (the next ``uptime`` re-reads the DB)."""
        for key in [k for k in self._uptime_db if k[0] == mcp_id]:
            del self._uptime_db[key]

    def _write(self, mcp_id: int, accs: dict[str, _Acc]) -> None:
        self.invalidate(mcp_id)
        with self._db.transaction() as conn:
            for key, a in accs.items():
                conn.execute(
                    _UPSERT,
                    (key, a.ok, a.total, a.latency_sum, a.latency_n, a.latency_max, mcp_id),
                )

    def flush(self) -> None:
        """Additively write every unflushed bucket, then clear them."""
        for mcp_id, live in self._live.items():
            if live.pending:
                self._write(mcp_id, live.pending)
                live.pending = {}

    def purge(self) -> int:
        """Delete minute buckets older than HISTORY_KEEP_DAYS; return how many."""
        cutoff = minute_key(self._clock.now() - timedelta(days=HISTORY_KEEP_DAYS))
        self._uptime_db.clear()
        return self._db.execute_rowcount("DELETE FROM mcp_minutes WHERE minute < ?", (cutoff,))

    def forget(self, mcp_id: int) -> None:
        self._live.pop(mcp_id, None)
        self.invalidate(mcp_id)

    # ---- transitions ----

    def record_transition(self, mcp_id: int, rec: TransitionRecord) -> None:
        self._db.execute(
            "INSERT INTO mcp_transitions (mcp_id, at, from_state, to_state, issue)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                mcp_id,
                _db_dt(rec.at),
                rec.from_state.value,
                rec.to_state.value,
                rec.issue.value if rec.issue else None,
            ),
        )

    def transitions(self, mcp_id: int, limit: int = 100) -> list[TransitionRecord]:
        """Newest first; equal timestamps are ordered by insertion (later first)."""
        rows = self._db.query(
            "SELECT at, from_state, to_state, issue FROM mcp_transitions"
            " WHERE mcp_id = ? ORDER BY at DESC, id DESC LIMIT ?",
            (mcp_id, limit),
        )
        return [
            TransitionRecord(
                at=_parse_dt(r["at"]),
                from_state=McpState(r["from_state"]),
                to_state=McpState(r["to_state"]),
                issue=Issue(r["issue"]) if r["issue"] else None,
            )
            for r in rows
        ]

    def recent_transitions(self, limit: int) -> list[tuple[int, TransitionRecord]]:
        """``(mcp_id, transition)`` across all MCPs, newest first (equal times: later insert first)."""
        rows = self._db.query(
            "SELECT mcp_id, at, from_state, to_state, issue FROM mcp_transitions"
            " ORDER BY at DESC, id DESC LIMIT ?",
            (limit,),
        )
        return [
            (
                r["mcp_id"],
                TransitionRecord(
                    at=_parse_dt(r["at"]),
                    from_state=McpState(r["from_state"]),
                    to_state=McpState(r["to_state"]),
                    issue=Issue(r["issue"]) if r["issue"] else None,
                ),
            )
            for r in rows
        ]

    # ---- actions ----

    def record_action(self, rec: ActionRecord) -> int:
        r = rec.result
        return self._db.execute(
            "INSERT INTO mcp_actions (run_id, mcp_id, at, requested, kind, trigger, reason,"
            " actor_id, status, exit_code, duration_ms, killed, error, stdout, stderr,"
            " stdout_truncated, stderr_truncated)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rec.run_id,
                rec.mcp_id,
                _db_dt(rec.at),
                rec.requested,
                rec.kind,
                rec.trigger,
                rec.reason,
                rec.actor_id,
                r.status,
                r.exit_code,
                r.duration_ms,
                r.killed,
                r.error,
                r.stdout,
                r.stderr,
                int(r.stdout_truncated),
                int(r.stderr_truncated),
            ),
        )

    def actions(self, mcp_id: int, limit: int = 50) -> list[ActionRecord]:
        """Newest first; equal timestamps are ordered by insertion (later first)."""
        rows = self._db.query(
            "SELECT * FROM mcp_actions WHERE mcp_id = ? ORDER BY at DESC, id DESC LIMIT ?",
            (mcp_id, limit),
        )
        return [_to_action(r) for r in rows]

    def recent_actions(self, limit: int) -> list[ActionRecord]:
        """Actions of all MCPs, newest first (equal times: later insert first)."""
        rows = self._db.query("SELECT * FROM mcp_actions ORDER BY at DESC, id DESC LIMIT ?", (limit,))
        return [_to_action(r) for r in rows]

    def action(self, mcp_id: int, action_id: int) -> ActionRecord | None:
        rows = self._db.query(
            "SELECT * FROM mcp_actions WHERE mcp_id = ? AND id = ?", (mcp_id, action_id)
        )
        return _to_action(rows[0]) if rows else None


def _to_action(r: sqlite3.Row) -> ActionRecord:
    return ActionRecord(
        id=r["id"],
        run_id=r["run_id"],
        mcp_id=r["mcp_id"],
        at=_parse_dt(r["at"]),
        requested=r["requested"],
        kind=r["kind"],
        trigger=r["trigger"],
        reason=r["reason"],
        actor_id=r["actor_id"],
        result=ScriptResult(
            status=r["status"],
            exit_code=r["exit_code"],
            duration_ms=r["duration_ms"],
            stdout=r["stdout"],
            stderr=r["stderr"],
            stdout_truncated=bool(r["stdout_truncated"]),
            stderr_truncated=bool(r["stderr_truncated"]),
            killed=r["killed"],
            error=r["error"],
            actual_sha256=None,
        ),
    )
