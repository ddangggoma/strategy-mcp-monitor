"""Local-only notice page API (V16): the page reports that a display was shown and acknowledged.

The credential is the per-attempt ``X-Notice-Token`` header, not a session cookie, so there is no
CSRF cookie check: a custom header cannot be sent cross-origin without a preflight, which this
app never answers. The request's TCP peer session (resolved by the server, never taken from the
request) must be the display's session. Every failure is 404 ``not_found`` so a response never
tells whether a token was valid; only a browser-marked cross-site fetch is 403 ``forbidden``, and
a live token whose peer cannot be resolved is 503 ``unavailable`` (retried; M2).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from app.notice.displays import DisplayNotFoundError
from app.services import Services
from app.web.deps import ApiError, get_services, resolved_peer

router = APIRouter()

TOKEN_HEADER = "X-Notice-Token"
_ALLOWED_FETCH_SITES = frozenset({"same-origin", "none"})


@dataclass(frozen=True)
class DisplayCaller:
    token: str
    peer_session: int | None


async def display_token(request: Request) -> DisplayCaller:
    token = request.headers.get(TOKEN_HEADER, "")
    if not token:
        raise ApiError(404, "not_found")
    site = request.headers.get("sec-fetch-site")
    if site is not None and site not in _ALLOWED_FETCH_SITES:
        raise ApiError(403, "forbidden")
    services = get_services(request)
    if not services.displays.knows(token):  # M1: no connection-table scan for a dead token
        raise ApiError(404, "not_found")
    peer = await resolved_peer(request)
    session = peer.session_id if peer is not None else None
    if session is None:  # M2: unresolved is not misuse; the page offers a retry
        raise ApiError(503, "unavailable")
    return DisplayCaller(token, session)


@router.post("/api/notice/display/open")
async def display_open(
    caller: DisplayCaller = Depends(display_token),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    try:
        display, content = services.displays.open(caller.token, caller.peer_session)
    except DisplayNotFoundError:
        raise ApiError(404, "not_found") from None
    return {
        "display_id": display.id,
        "version": display.version,
        "title": content.title,
        "body": content.body,
        "button_text": content.button_text,
    }


@router.post("/api/notice/display/ack", status_code=204)
async def display_ack(
    caller: DisplayCaller = Depends(display_token),
    services: Services = Depends(get_services),
) -> Response:
    try:
        services.displays.acknowledge(caller.token, caller.peer_session)
    except DisplayNotFoundError:
        raise ApiError(404, "not_found") from None
    return Response(status_code=204)
