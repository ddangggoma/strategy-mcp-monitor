"""Local-only API of the per-session agent (V4, ruling C2).

Every route authenticates with the per-launch ``X-Agent-Token`` header plus the request's TCP peer
session, which the server resolves itself (``peer_of``); nothing the agent claims is trusted. A
browser page cannot send the custom header cross-origin (no preflight is ever answered) and
``LocalHostGuard`` refuses rebound hosts. Errors: 401 ``login_required``, 403 ``forbidden``,
422 ``validation`` only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt

from app.activity.agent_hub import AGENT_TOKEN_HEADER, AgentAuthError, AgentSlot
from app.services import Services
from app.web.deps import ApiError, get_services, peer_of
from app.win.peer import PeerInfo

router = APIRouter()

EVENTS_MAX = 200
DisplayId = Annotated[int, Path(ge=1, le=2**63 - 1)]  # SQLite INTEGER range; larger overflows


class HelloBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: Annotated[StrictInt, Field(ge=0)]
    pid: Annotated[StrictInt, Field(ge=1)]
    version: Annotated[str, Field(max_length=40)]


class HeartbeatBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idle_sec: Annotated[StrictInt, Field(ge=0)] | None = None
    locked: StrictBool | None = None


class WindowEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["foreground", "minimize", "restore", "title"]
    at: AwareDatetime
    pid: Annotated[StrictInt, Field(ge=0)]
    exe: Annotated[str, Field(max_length=260)] | None
    title: Annotated[str, Field(max_length=512)]


class IdleEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["idle", "active"]
    at: AwareDatetime
    idle_sec: Annotated[StrictInt, Field(ge=0)]


class EventsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: Annotated[
        list[Annotated[WindowEventIn | IdleEventIn, Field(discriminator="type")]],
        Field(max_length=EVENTS_MAX),
    ]


@dataclass(frozen=True)
class AgentCaller:
    slot: AgentSlot
    peer: PeerInfo


async def agent_slot(request: Request) -> AgentCaller:
    services = get_services(request)
    token = request.headers.get(AGENT_TOKEN_HEADER)
    try:
        if not token:  # no connection-table scan for a request that cannot authenticate
            services.agents.authenticate(None, None)
        peer = await peer_of(request)
        slot = services.agents.authenticate(token, peer)
    except AgentAuthError as exc:
        raise ApiError(exc.status, exc.code) from None
    assert peer is not None  # authenticate refuses a request without a resolved peer
    return AgentCaller(slot, peer)


Caller = Annotated[AgentCaller, Depends(agent_slot)]
Svc = Annotated[Services, Depends(get_services)]


@router.post("/api/agent/hello")
async def agent_hello(body: HelloBody, caller: Caller, services: Svc) -> dict[str, Any]:
    try:
        return services.agents.hello(
            caller.slot, session_id=body.session_id, pid=body.pid, version=body.version,
            peer=caller.peer,
        )
    except AgentAuthError as exc:
        raise ApiError(exc.status, exc.code) from None


@router.get("/api/agent/next", response_model=None)
async def agent_next(
    caller: Caller, services: Svc,
    timeout: Annotated[float, Query(ge=0, le=30, allow_inf_nan=False)] = 25,
) -> dict[str, Any] | Response:
    command = await services.agents.next(caller.slot, timeout)
    return command if command is not None else Response(status_code=204)


@router.post("/api/agent/heartbeat", status_code=204)
async def agent_heartbeat(body: HeartbeatBody, caller: Caller, services: Svc) -> Response:
    services.agents.heartbeat(caller.slot, idle_sec=body.idle_sec, locked=body.locked)
    return Response(status_code=204)


@router.post("/api/agent/events", status_code=204)
async def agent_events(body: EventsBody, caller: Caller, services: Svc) -> Response:
    services.agents.events(caller.slot, body.events)
    return Response(status_code=204)


@router.post("/api/agent/notice/{display_id}/closed", status_code=204)
async def agent_notice_closed(display_id: DisplayId, caller: Caller, services: Svc) -> Response:
    services.agents.closed(caller.slot, display_id)
    return Response(status_code=204)
