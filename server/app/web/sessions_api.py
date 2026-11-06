"""RDP session routes on both channels (``view_session_history``, V31): current sessions, the
connection history with logon failures, and the collectors' health."""
from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.auth.policy import Action
from app.clock import to_kst_iso
from app.collect.manager import CollectorStatus
from app.services import Services
from app.sessions.history import Connection, LogonFailure
from app.users.store import User
from app.web.deps import get_services, require

router = APIRouter()

RowId = Annotated[int, Query(ge=1, le=2**63 - 1)]  # SQLite INTEGER range; larger overflows


def connection_json(c: Connection) -> dict[str, Any]:
    return {
        "id": c.id,
        "session_id": c.session_id,
        "user": c.user,
        "domain": c.domain,
        "client_name": c.client_name,
        "client_ip": c.client_ip,
        "reverse_dns": c.reverse_dns,
        "client_build": c.client_build,
        "protocol": c.protocol,
        "resolution": c.resolution,
        "kind": c.kind,
        "logon_at": to_kst_iso(c.logon_at) if c.logon_at is not None else None,
        "connected_at": to_kst_iso(c.connected_at),
        "ended_at": to_kst_iso(c.ended_at) if c.ended_at is not None else None,
        "end_reason": c.end_reason,
        "first_seen_ip": c.first_seen_ip,
        "first_seen_device": c.first_seen_device,
        "notice": None,  # the latest notice display of the connection: Task 11
    }


def failure_json(f: LogonFailure) -> dict[str, Any]:
    return {
        "id": f.id,
        "at": to_kst_iso(f.at),
        "user": f.user,
        "domain": f.domain,
        "client_ip": f.client_ip,
        "workstation": f.workstation,
        "logon_type": f.logon_type,
        "status": f.status,
        "sub_status": f.sub_status,
        "source": f.source,
    }


def collector_json(s: CollectorStatus) -> dict[str, Any]:
    return {"name": s.name, "ok": s.ok, "error": s.error, "since": to_kst_iso(s.since)}


@router.get("/api/sessions/current")
async def sessions_current(
    _user: User | None = Depends(require(Action.VIEW_SESSION_HISTORY)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    """Every watched session, disconnected ones included; ``ready`` is false before the first snapshot."""
    return {"ready": services.rdp.ready, "sessions": services.rdp.current()}


@router.get("/api/sessions/history")
async def sessions_history(
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    before_id: RowId | None = None,
    _user: User | None = Depends(require(Action.VIEW_SESSION_HISTORY)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    """Connections newest first, paged by ``before_id``. The logon failures of the window come with
    the first page only (the cursor pages connections, so later pages would repeat them)."""
    since = services.clock.now() - timedelta(days=days)
    history = services.rdp_history
    rows = history.connections(since, limit, before_id)
    failures = history.failures(since, limit) if before_id is None else []
    return {
        "connections": [connection_json(c) for c in rows],
        "failures": [failure_json(f) for f in failures],
        "next_before_id": rows[-1].id if len(rows) == limit else None,
    }


@router.get("/api/sessions/collectors")
async def sessions_collectors(
    _user: User | None = Depends(require(Action.VIEW_SESSION_HISTORY)),
    services: Services = Depends(get_services),
) -> list[dict[str, Any]]:
    return [collector_json(s) for s in services.collectors.status()]
