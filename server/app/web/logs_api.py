"""Log and audit search on both channels (rulings W7, W11–W13): pages, histograms, user facets, the
index status and CSV/JSONL exports, all read from ``data/index.db``.

Every index read runs in a worker thread inside one of ``LogIndex.query_slots``
(:meth:`app.logstore.indexer.LogIndex.query`). First pages (no cursor) are recorded as
``logs_view``/``audit_view`` at most once a minute per user, channel and filter set; every export is
recorded (W11).
"""
from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
from collections import OrderedDict
from collections.abc import AsyncIterator, Hashable, Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.auth.policy import Action
from app.clock import KST, Clock, to_kst_iso
from app.logstore.fts import InvalidQuery
from app.logstore.indexer import QueryTimeout
from app.logstore.query import DEFAULT_PAGE, MAX_PAGE, LogFilter, LogRow, decode_cursor
from app.services import Services
from app.users.store import User
from app.web.deps import ApiError, client_ip, get_channel, get_services, require

router = APIRouter()

EXPORT_CHUNK = 1000
MAX_EXPORT = 100_000
CSV_COLUMNS = ("ts", "cat", "event", "user", "session_id", "client_ip", "client_name", "outcome", "summary")
SUMMARY_KEYS = ("text", "cmdline", "title", "exe", "name", "email", "action")
SUMMARY_MAX_CHARS = 2000
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")  # a spreadsheet would run the cell (W12)
AUDIT_KINDS: dict[str, tuple[str, ...]] = {
    "admin": ("admin.audit",), "auth": ("auth",), "all": ("admin.audit", "auth"),
}

# A 422 `validation` that ran out of time (not a bad parameter) says so in this header (I2).
QUERY_TIMEOUT_REASON = "query_timeout"

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MS = timedelta(milliseconds=1)
_CONTENT_TYPES = {"csv": "text/csv; charset=utf-8", "jsonl": "application/x-ndjson; charset=utf-8"}

ExportFormat = Literal["csv", "jsonl"]


class ViewAuditThrottle:
    """Allows a key once per ``window_sec``; remembers at most ``max_keys`` keys (oldest dropped)."""

    def __init__(self, clock: Clock, window_sec: float = 60, max_keys: int = 1000) -> None:
        self._clock = clock
        self._window = timedelta(seconds=window_sec)
        self._max_keys = max_keys
        self._last: OrderedDict[Hashable, datetime] = OrderedDict()  # oldest allowance first

    def __len__(self) -> int:
        return len(self._last)

    def allow(self, key: Hashable) -> bool:
        now = self._clock.now()
        last = self._last.get(key)
        if last is not None and now - last < self._window:
            return False
        self._last.pop(key, None)
        while len(self._last) >= self._max_keys:
            self._last.popitem(last=False)
        self._last[key] = now
        return True


# -- filters ---------------------------------------------------------------------------------------

def _validation() -> ApiError:
    return ApiError(422, "validation")


def _instant(value: str) -> datetime:
    """An ISO 8601 time with an offset (W8: inputs without one are refused)."""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise _validation() from None
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise _validation()
    return dt


def _span(services: Services, from_: str | None, to: str | None) -> tuple[int, int]:
    """``[from, to)`` in UTC epoch ms; ``to`` defaults to now and ``from`` to an hour before ``to``."""
    try:
        end = _instant(to) if to is not None else services.clock.now()
        start = _instant(from_) if from_ is not None else end - timedelta(hours=1)
        return (start - _EPOCH) // _MS, (end - _EPOCH) // _MS
    except OverflowError:  # an hour before year 1
        raise _validation() from None


def _make_filter(**kw: Any) -> LogFilter:
    try:
        return LogFilter(**kw)
    except InvalidQuery:
        raise _validation() from None


def log_filter(
    request: Request,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    users: list[str] = Query([]),
    cat: list[str] = Query([]),
    event: list[str] = Query([]),
    outcome: list[str] = Query([]),
    session: int | None = Query(None, ge=0, le=2**31 - 1),
    ip: str | None = Query(None, min_length=1, max_length=64),
    q: str | None = Query(None, max_length=500),
) -> LogFilter:
    from_ms, to_ms = _span(get_services(request), from_, to)
    return _make_filter(from_ms=from_ms, to_ms=to_ms, users=tuple(users), cats=tuple(cat),
                        events=tuple(event), outcomes=tuple(outcome), session_id=session,
                        client_ip=ip, q=q)


@dataclass(frozen=True)
class AuditFilter:
    filter: LogFilter
    kind: str


def audit_filter(
    request: Request,
    kind: Literal["admin", "auth", "all"] = "admin",
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    users: list[str] = Query([]),
    result: list[str] = Query([]),
    channel: Literal["local", "external"] | None = None,
    q: str | None = Query(None, max_length=500),
) -> AuditFilter:
    """``/api/audit``: ``admin.audit`` and/or ``auth`` rows (W13); ``result`` is the outcome."""
    from_ms, to_ms = _span(get_services(request), from_, to)
    f = _make_filter(from_ms=from_ms, to_ms=to_ms, users=tuple(users), cats=AUDIT_KINDS[kind],
                     outcomes=tuple(result), channel=channel, q=q)
    return AuditFilter(f, kind)


def _kst(ms: int) -> str:
    return to_kst_iso(_EPOCH + ms * _MS)


def filters_json(f: LogFilter, kind: str | None = None) -> dict[str, Any]:
    """The conditions of a request for its audit line: the non-empty ones, times in KST. An audit
    request is described by its ``kind`` instead of the categories it implies."""
    out: dict[str, Any] = {
        "from": _kst(f.from_ms), "to": _kst(f.to_ms), "users": list(f.users),
        "cat": [] if kind is not None else list(f.cats), "event": list(f.events),
        "outcome": list(f.outcomes), "session": f.session_id, "ip": f.client_ip, "q": f.q,
        "kind": kind, "channel": f.channel,
    }
    return {k: v for k, v in out.items() if v is not None and v != [] and v != ""}


# -- reads -----------------------------------------------------------------------------------------

async def _run(services: Services, fn: Any, *args: Any) -> Any:
    try:
        return await services.log_index.query(fn, *args)
    except QueryTimeout:  # interrupted at the time limit (I2): narrow the filter, no new error code
        raise ApiError(422, "validation", headers={"X-Error-Reason": QUERY_TIMEOUT_REASON}) from None
    except InvalidQuery:  # a bad cursor, bucket count or limit
        raise _validation() from None


def log_item(row: LogRow) -> dict[str, Any]:
    return {
        "id": row.id, "ts": _kst(row.ts_ms), "cat": row.cat, "event": row.event, "user": row.user,
        "session_id": row.session_id, "client_ip": row.client_ip, "outcome": row.outcome, "data": row.data,
    }


async def _page(services: Services, f: LogFilter, cursor: str | None, limit: int) -> dict[str, Any]:
    try:
        after = decode_cursor(cursor) if cursor is not None else None
    except InvalidQuery:
        raise _validation() from None
    page = await _run(services, services.log_index.reader().page, f, after, limit)
    return {
        "items": [log_item(r) for r in page.rows],
        "next_cursor": page.next_cursor,
        "index": {"ready": services.log_index.status().ready},
    }


def _record_view(request: Request, user: User | None, action: str, filters: dict[str, Any]) -> None:
    """A first-page view, at most once per ``ViewAuditThrottle`` window per user, channel and filters."""
    channel = get_channel(request)
    digest = hashlib.sha256(json.dumps(filters, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    throttle: ViewAuditThrottle = request.app.state.view_audit_throttle
    if throttle.allow((user.id if user else None, channel, digest)):
        get_services(request).audit.admin(user, action, channel, client_ip(request), {"filters": filters}, "ok")


Limit = Annotated[int, Query(ge=1, le=MAX_PAGE)]


@router.get("/api/logs")
async def logs_page(
    request: Request,
    user: User | None = Depends(require(Action.VIEW_LOGS)),
    f: LogFilter = Depends(log_filter),
    cursor: str | None = None,
    limit: Limit = DEFAULT_PAGE,
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    """Newest first; ``next_cursor`` continues the list (W7)."""
    body = await _page(services, f, cursor, limit)
    if cursor is None:
        _record_view(request, user, "logs_view", filters_json(f))
    return body


@router.get("/api/logs/histogram")
async def logs_histogram(
    _user: User | None = Depends(require(Action.VIEW_LOGS)),
    f: LogFilter = Depends(log_filter),
    buckets: Annotated[int, Query(ge=10, le=200)] = 60,
    group: Literal["none", "cat", "user"] = "none",
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    h = await _run(services, services.log_index.reader().histogram, f, buckets, group)
    return {
        "from": _kst(h.start_ms),
        "to": _kst(h.to_ms),
        "bucket_sec": h.bucket_sec,
        "starts": [_kst(s) for s in h.starts_ms],
        "series": [{"key": key, "counts": counts} for key, counts in h.series],
        "total": h.total,
        "source": h.source,
    }


@router.get("/api/logs/users")
async def logs_users(
    _user: User | None = Depends(require(Action.VIEW_LOGS)),
    f: LogFilter = Depends(log_filter),
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    services: Services = Depends(get_services),
) -> list[dict[str, Any]]:
    """Rows per user under the filter, its ``users`` condition left out; most first."""
    counts = await _run(services, services.log_index.reader().users, f, limit)
    return [{"user": user, "count": n} for user, n in counts]


@router.get("/api/logs/status")
async def logs_status(
    _user: User | None = Depends(require(Action.VIEW_LOGS)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    st = services.log_index.status()
    body = asdict(st)
    body["last_indexed_at"] = to_kst_iso(st.last_indexed_at) if st.last_indexed_at is not None else None
    return body


@router.get("/api/audit")
async def audit_page(
    request: Request,
    user: User | None = Depends(require(Action.VIEW_AUDIT)),
    a: AuditFilter = Depends(audit_filter),
    cursor: str | None = None,
    limit: Limit = DEFAULT_PAGE,
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    body = await _page(services, a.filter, cursor, limit)
    if cursor is None:
        _record_view(request, user, "audit_view", filters_json(a.filter, a.kind))
    return body


# -- exports ---------------------------------------------------------------------------------------

def _cell(value: object) -> str:
    """A CSV cell: empty for None; a leading formula character is neutralized with ``'`` (W12)."""
    if value is None:
        return ""
    text = str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def _summary(data: dict[str, Any]) -> str | None:
    for key in SUMMARY_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value[:SUMMARY_MAX_CHARS]
    return None


def _csv(rows: list[LogRow], header: bool = False) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    if header:
        writer.writerow(CSV_COLUMNS)
    for r in rows:
        writer.writerow([_cell(v) for v in (
            _kst(r.ts_ms), r.cat, r.event, r.user, r.session_id, r.client_ip, r.data.get("client_name"),
            r.outcome, _summary(r.data),
        )])
    return buf.getvalue()


def _jsonl(rows: list[LogRow]) -> str:
    return "".join(r.raw + "\n" for r in rows)


class _Batches:
    """An ``iter_rows`` generator pulled ``EXPORT_CHUNK`` rows at a time (one worker thread per pull,
    never two at once: each pull is awaited through ``LogIndex.query``, which outlives cancellation)."""

    def __init__(self, rows: Iterator[LogRow]) -> None:
        self._rows = rows

    def take(self) -> list[LogRow]:
        return list(itertools.islice(self._rows, EXPORT_CHUNK))

    def close(self) -> None:
        """Close the generator and its connection (a no-op once the rows ran out)."""
        self._rows.close()  # type: ignore[attr-defined]


def _stamp(ms: int) -> str:
    return (_EPOCH + ms * _MS).astimezone(KST).strftime("%Y%m%d-%H%M")


async def _export(
    request: Request, user: User | None, services: Services, f: LogFilter, fmt: ExportFormat, limit: int,
    name: str, action: str, filters: dict[str, Any],
) -> StreamingResponse:
    batches = _Batches(services.log_index.reader().iter_rows(f, limit, chunk=EXPORT_CHUNK))
    try:
        first: list[LogRow] = await _run(services, batches.take)  # fail before the 200 is sent
    except BaseException:
        batches.close()
        raise
    channel = get_channel(request)
    services.audit.admin(user, action, channel, client_ip(request),
                         {"filters": filters, "format": fmt, "limit": limit}, "ok")
    encode = _jsonl if fmt == "jsonl" else _csv

    async def body() -> AsyncIterator[bytes]:
        try:
            if fmt == "csv":
                yield ("﻿" + _csv([], header=True)).encode("utf-8")
            batch = first
            while batch:
                yield encode(batch).encode("utf-8")
                if len(batch) < EXPORT_CHUNK:
                    break
                batch = await _run(services, batches.take)
        finally:
            batches.close()

    filename = f"mcp-{name}-{_stamp(f.from_ms)}-{_stamp(f.to_ms)}.{fmt}"
    return StreamingResponse(body(), media_type=_CONTENT_TYPES[fmt], headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    })


ExportLimit = Annotated[int, Query(ge=1, le=MAX_EXPORT)]


@router.get("/api/logs/export")
async def logs_export(
    request: Request,
    format: ExportFormat,
    user: User | None = Depends(require(Action.EXPORT_LOGS)),
    f: LogFilter = Depends(log_filter),
    limit: ExportLimit = MAX_EXPORT,
    services: Services = Depends(get_services),
) -> StreamingResponse:
    return await _export(request, user, services, f, format, limit, "logs", "logs_export", filters_json(f))


@router.get("/api/audit/export")
async def audit_export(
    request: Request,
    format: ExportFormat,
    user: User | None = Depends(require(Action.EXPORT_LOGS)),
    _viewer: User | None = Depends(require(Action.VIEW_AUDIT)),  # an audit export is also a view (minor 6)
    a: AuditFilter = Depends(audit_filter),
    limit: ExportLimit = MAX_EXPORT,
    services: Services = Depends(get_services),
) -> StreamingResponse:
    return await _export(request, user, services, a.filter, format, limit, "audit", "audit_export",
                         filters_json(a.filter, a.kind))
