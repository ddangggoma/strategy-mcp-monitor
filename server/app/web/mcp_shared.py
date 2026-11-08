"""MCP routes served on both channels: board, SSE stream, detail/history, settings, manual actions."""
from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from datetime import timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from app.auth.policy import Action, can
from app.clock import to_kst_iso
from app.monitor.bus import BoardBus, IpStreamLimitError, StreamLimitError, Subscription
from app.monitor.engine import ActionInProgressError
from app.monitor.history import ActionRecord
from app.monitor.models import Mcp
from app.monitor.store import EndpointTakenError, McpNotFoundError, NameTakenError
from app.monitor.supervisor import Monitor
from app.services import Services
from app.users.store import User
from app.web.channels import Channel
from app.web.deps import ApiError, client_ip, get_channel, get_services, require, user_summary

router = APIRouter()

COALESCE_SEC = 1.0
HEARTBEAT_SEC = 15.0
STREAM_RETRY_AFTER_SEC = 5
HISTORY_TRANSITIONS = 200
HISTORY_ACTIONS = 100

UserCache = dict[int | None, dict[str, object] | None]

McpId = Annotated[int, Path(ge=1, le=2**63 - 1)]  # SQLite INTEGER range; larger overflows


# ---- serialization -----------------------------------------------------------------


def mcp_detail(services: Services, mcp: Mcp) -> dict[str, Any]:
    """Full detail: every McpConfig field, id, effective owner, creation time and the live board item.

    ``config_error`` is true for a stored config that fails validation (M6): the fields are the
    stored values, ``live`` is None (it is not monitored) and a PUT that fixes it starts monitoring.
    """
    owner_id = services.mcps.effective_owner_id(mcp)
    owner = services.users.get(owner_id) if owner_id is not None else None
    return {
        **mcp.config.model_dump(warnings=False),  # an invalid stored config may mismatch the types
        "id": mcp.id,
        "config_error": mcp.config_error is not None,
        "owner": {"id": owner.id, "email": owner.email, "name": owner.name} if owner else None,
        "created_at": to_kst_iso(mcp.created_at),
        "live": services.monitor.board_item(mcp.id),
    }


def cached_user_summary(
    services: Services, user_id: int | None, cache: UserCache | None
) -> dict[str, object] | None:
    """``user_summary`` memoized in ``cache`` (one per request) when given."""
    if cache is None:
        return user_summary(services, user_id)
    if user_id not in cache:
        cache[user_id] = user_summary(services, user_id)
    return cache[user_id]


def _action_json(services: Services, a: ActionRecord, users: UserCache | None = None) -> dict[str, Any]:
    return {
        "id": a.id,
        "run_id": a.run_id,
        "at": to_kst_iso(a.at),
        "requested": a.requested,
        "kind": a.kind,
        "trigger": a.trigger,
        "reason": a.reason,
        "actor_id": a.actor_id,
        "actor": cached_user_summary(services, a.actor_id, users),
        "status": a.result.status,
        "exit_code": a.result.exit_code,
        "duration_ms": a.result.duration_ms,
        "killed": a.result.killed,
        "error": a.result.error,
    }


def _get_mcp(services: Services, mcp_id: int) -> Mcp:
    mcp = services.mcps.get(mcp_id)
    if mcp is None:
        raise ApiError(404, "not_found")
    return mcp


# ---- board + SSE -------------------------------------------------------------------


@router.get("/api/board")
async def board(
    _user: User | None = Depends(require(Action.VIEW_BOARD)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    return board_snapshot(services)


def board_snapshot(services: Services) -> dict[str, Any]:
    """The board (GET /api/board, the first SSE event): MCPs, plus ``sessions`` once collected and
    this PC's resources (``system``) once read.

    ``sessions`` is absent before the first WTS snapshot and when session collection is off (V7);
    ``system`` is absent before the first reading (later ones arrive as SSE ``system`` events).
    """
    snapshot = services.monitor.board_snapshot()
    sessions = services.rdp.board_sessions()
    if sessions is not None:
        snapshot["sessions"] = sessions
    system = services.system.latest
    if system is not None:
        snapshot["system"] = system
    return snapshot


def _sse(name: str, data: Any) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


async def board_stream(
    monitor: Monitor,
    bus: BoardBus,
    sub: Subscription,
    *,
    snapshot: Callable[[], dict[str, Any]] | None = None,
    coalesce_sec: float = COALESCE_SEC,
    heartbeat_sec: float = HEARTBEAT_SEC,
) -> AsyncGenerator[str]:
    """SSE text for one subscriber: the whole board first, then changes coalesced per ``coalesce_sec``.

    ``snapshot`` builds the first ``board`` event (default: ``monitor.board_snapshot``).
    """
    loop = asyncio.get_running_loop()
    try:
        sub.dirty.clear()  # the snapshot below covers anything marked so far
        yield _sse("board", snapshot() if snapshot is not None else monitor.board_snapshot())
        last_sent = last_output = loop.time()
        while True:
            if not sub.dirty and not sub.events:
                sub.wake.clear()
                try:
                    await asyncio.wait_for(
                        sub.wake.wait(), max(0.0, last_output + heartbeat_sec - loop.time())
                    )
                except TimeoutError:
                    yield ": ping\n\n"
                    last_output = loop.time()
                    continue
            hold = last_sent + coalesce_sec - loop.time()
            if hold > 0:
                await asyncio.sleep(hold)  # let a burst of changes pile up into one event
            dirty, sub.dirty = sorted(sub.dirty), set()
            events = list(sub.events)
            sub.events.clear()
            for mcp_id in dirty:
                item = monitor.batch_item(mcp_id)  # built once per change, shared by all streams
                yield _sse("mcp", item) if item is not None else _sse("mcp_removed", {"id": mcp_id})
            for name, data in events:
                yield _sse(name, data)
            last_sent = last_output = loop.time()
    finally:
        bus.unsubscribe(sub)


async def open_stream(services: Services, *, authed: bool, ip: str | None) -> AsyncIterator[str]:
    """The route's body: subscribe on the first step, always unsubscribe when the stream ends.

    Subscribing here, not in the route, means a response that never starts (client gone before
    the first byte) holds no slot.
    """
    bus = services.bus
    try:
        sub = bus.subscribe(authed=authed, ip=ip)
    except StreamLimitError:
        return  # lost the race for the last slot after the route's pre-flight check
    try:
        async with contextlib.aclosing(
            board_stream(
                services.monitor, bus, sub, snapshot=lambda: board_snapshot(services),
                coalesce_sec=COALESCE_SEC, heartbeat_sec=HEARTBEAT_SEC,
            )
        ) as inner:
            async for chunk in inner:
                yield chunk
    finally:
        bus.unsubscribe(sub)


@router.get("/api/stream")
async def stream(
    request: Request,
    user: User | None = Depends(require(Action.VIEW_BOARD)),
    services: Services = Depends(get_services),
    channel: Channel = Depends(get_channel),
) -> StreamingResponse:
    ip = client_ip(request)
    try:
        services.bus.check_capacity(ip)
    except IpStreamLimitError:
        raise ApiError(429, "rate_limited", {"Retry-After": str(STREAM_RETRY_AFTER_SEC)}) from None
    except StreamLimitError:
        raise ApiError(503, "too_many_streams") from None
    # Action events carry exit codes and run ids: only subscribers who may read MCP history get them.
    authed = can(user, Action.VIEW_MCP_HISTORY, channel)
    return StreamingResponse(
        open_stream(services, authed=authed, ip=ip),
        media_type="text/event-stream",  # Starlette appends "; charset=utf-8" for text/*
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# ---- detail / history --------------------------------------------------------------


@router.get("/api/mcps")
async def list_mcps(
    _user: User | None = Depends(require(Action.VIEW_MCP_HISTORY)),
    services: Services = Depends(get_services),
) -> list[dict[str, Any]]:
    return [mcp_detail(services, m) for m in services.mcps.list()]


@router.get("/api/mcps/{mcp_id}")
async def get_mcp(
    mcp_id: McpId,
    _user: User | None = Depends(require(Action.VIEW_MCP_HISTORY)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    return mcp_detail(services, _get_mcp(services, mcp_id))


@router.get("/api/mcps/{mcp_id}/history")
async def mcp_history(
    mcp_id: McpId,
    hours: Annotated[int, Query(ge=1, le=168)] = 24,
    _user: User | None = Depends(require(Action.VIEW_MCP_HISTORY)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    _get_mcp(services, mcp_id)
    since = services.clock.now() - timedelta(hours=hours)
    history = services.history
    users: UserCache = {}
    return {
        "buckets": [
            {
                "minute": to_kst_iso(b.minute),
                "ok": b.ok,
                "total": b.total,
                "avg_latency_ms": b.avg_latency_ms,
                "max_latency_ms": b.max_latency_ms,
            }
            for b in history.buckets(mcp_id, since)
        ],
        "transitions": [
            {
                "at": to_kst_iso(t.at),
                "from": t.from_state.value,
                "to": t.to_state.value,
                "issue": t.issue.value if t.issue else None,
            }
            for t in history.transitions(mcp_id, HISTORY_TRANSITIONS)
            if t.at >= since
        ],
        "actions": [
            _action_json(services, a, users)
            for a in history.actions(mcp_id, HISTORY_ACTIONS)
            if a.at >= since
        ],
    }


@router.get("/api/mcp-activity")
async def mcp_activity(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    _user: User | None = Depends(require(Action.VIEW_MCP_HISTORY)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    """The latest state transitions and script actions across every MCP, newest first."""
    names = {m.id: m.config.name for m in services.mcps.list()}
    users: UserCache = {}
    history = services.history
    return {
        "transitions": [
            {
                "mcp_id": mcp_id,
                "name": names.get(mcp_id),
                "at": to_kst_iso(t.at),
                "from": t.from_state.value,
                "to": t.to_state.value,
                "issue": t.issue.value if t.issue else None,
            }
            for mcp_id, t in history.recent_transitions(limit)
        ],
        "actions": [
            {**_action_json(services, a, users), "mcp_id": a.mcp_id, "name": names.get(a.mcp_id)}
            for a in history.recent_actions(limit)
        ],
    }


@router.get("/api/mcps/{mcp_id}/actions/{action_id}")
async def mcp_action_detail(
    mcp_id: McpId,
    action_id: McpId,
    _user: User | None = Depends(require(Action.VIEW_MCP_HISTORY)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    record = services.history.action(mcp_id, action_id)
    if record is None:
        raise ApiError(404, "not_found")
    r = record.result
    return {
        **_action_json(services, record),
        "stdout": r.stdout,
        "stderr": r.stderr,
        "stdout_truncated": r.stdout_truncated,
        "stderr_truncated": r.stderr_truncated,
    }


# ---- settings + manual actions -----------------------------------------------------


@router.put("/api/mcps/{mcp_id}")
async def update_mcp(
    mcp_id: McpId,
    body: dict[str, Any],
    request: Request,
    actor: User | None = Depends(require(Action.EDIT_MCP_SETTINGS)),
    services: Services = Depends(get_services),
    channel: Channel = Depends(get_channel),
) -> dict[str, Any]:
    ip = client_ip(request)
    try:
        before, after = services.mcps.update(mcp_id, body)
    except (McpNotFoundError, ValidationError, NameTakenError, EndpointTakenError) as exc:
        status, code = {
            McpNotFoundError: (404, "not_found"),
            ValidationError: (422, "validation"),
            NameTakenError: (409, "name_taken"),
            EndpointTakenError: (409, "endpoint_taken"),
        }[type(exc)]
        services.audit.admin(
            actor=actor, action="mcp_update", channel=channel, ip=ip,
            target={"mcp_id": mcp_id, "error": code}, result="error",
        )
        raise ApiError(status, code) from None
    if services.monitor.engine(mcp_id) is None:
        services.monitor.add(after)  # a fixed config_error row (never monitored): start monitoring it
    else:
        services.monitor.reconfigure(after)
    old, new = before.config.model_dump(warnings=False), after.config.model_dump()
    changes = {k: [old[k], v] for k, v in new.items() if old[k] != v}
    if changes:
        services.audit.admin(
            actor=actor, action="mcp_update", channel=channel, ip=ip,
            target={"mcp_id": mcp_id, "changes": changes}, result="ok",
        )
    return mcp_detail(services, after)


@router.post("/api/mcps/{mcp_id}/actions/{kind}", status_code=202)
async def mcp_manual_action(
    mcp_id: McpId,
    kind: Literal["start", "restart", "stop"],
    request: Request,
    actor: User | None = Depends(require(Action.MCP_MANUAL_ACTION)),
    services: Services = Depends(get_services),
    channel: Channel = Depends(get_channel),
) -> JSONResponse:
    assert actor is not None  # require() denies anonymous
    ip = client_ip(request)
    try:
        run_id = services.monitor.manual_action(mcp_id, kind, actor)
    except (McpNotFoundError, ActionInProgressError) as exc:
        status, code = (404, "not_found") if isinstance(exc, McpNotFoundError) else (409, "action_in_progress")
        services.audit.admin(
            actor=actor, action="mcp_action", channel=channel, ip=ip,
            target={"mcp_id": mcp_id, "kind": kind, "error": code}, result="error",
        )
        raise ApiError(status, code) from None
    services.audit.admin(
        actor=actor, action="mcp_action", channel=channel, ip=ip,
        target={"mcp_id": mcp_id, "kind": kind, "run_id": run_id}, result="ok",
    )
    return JSONResponse({"run_id": run_id}, status_code=202)
