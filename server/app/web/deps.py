from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import JSONResponse

from app.auth.policy import Action, can
from app.auth.sessions import AuthSession
from app.users.store import User
from app.web.channels import Channel

if TYPE_CHECKING:
    from app.services import Services

# One cookie name per channel: a browser keeps both for the same host (cookies ignore ports),
# so a shared name would let one channel's login overwrite or clear the other's.
SESSION_COOKIES: Mapping[Channel, str] = {"local": "mcpmon_sid_local", "external": "mcpmon_sid_ext"}
CSRF_HEADER = "X-CSRF-Token"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def session_cookie_name(channel: Channel) -> str:
    return SESSION_COOKIES[channel]


class ApiError(Exception):
    """Raised by routes/deps; rendered as exactly {"error": "<code>"} (no FastAPI "detail" wrapper)."""

    def __init__(self, status_code: int, code: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.headers = headers


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse({"error": exc.code}, status_code=exc.status_code, headers=exc.headers)


def get_channel(request: Request) -> Channel:
    return request.app.state.channel


def get_services(request: Request) -> Services:
    return request.app.state.services


def user_json(user: User) -> dict[str, object]:
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role}


def user_summary(services: Services, user_id: int | None) -> dict[str, object] | None:
    """``{"id", "email", "name"}`` of a user, or None for no id / an unknown user."""
    if user_id is None:
        return None
    user = services.users.get(user_id)
    if user is None:
        return None
    return {"id": user.id, "email": user.email, "name": user.name}


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _resolve(request: Request) -> User | None:
    """Resolve (once per request) the logged-in user and stash their session for CSRF checks.

    A session whose user is missing or inactive is treated as anonymous.
    """
    state = request.state
    if getattr(state, "_auth_resolved", False):
        return state.auth_user
    services = get_services(request)
    user: User | None = None
    session: AuthSession | None = None
    channel = get_channel(request)
    sid = request.cookies.get(session_cookie_name(channel))
    if sid:
        found = services.sessions.get(sid, channel)
        if found is not None:
            candidate = services.users.get(found.user_id)
            if candidate is not None and candidate.active:
                user, session = candidate, found
    state.auth_user = user
    state.auth_session = session
    state._auth_resolved = True
    return user


async def current_user(request: Request) -> User | None:
    return _resolve(request)


def _verify_csrf(request: Request, action_name: str) -> None:
    user = _resolve(request)
    session: AuthSession | None = request.state.auth_session
    if session is None or request.method not in _UNSAFE_METHODS:
        return
    supplied = request.headers.get(CSRF_HEADER, "")
    if hmac.compare_digest(supplied.encode("utf-8"), session.csrf_token.encode("utf-8")):
        return
    get_services(request).audit.admin(
        actor=user,
        action=action_name,
        channel=get_channel(request),
        ip=client_ip(request),
        target={"path": request.url.path, "reason": "csrf"},
        result="denied",
    )
    raise ApiError(403, "csrf")


async def check_csrf(request: Request) -> None:
    """For unsafe methods with a live session, require a matching X-CSRF-Token header."""
    _verify_csrf(request, "csrf")


def require(
    action: Action, owner_id: Callable[[Request], int | None] | None = None
) -> Callable[[Request], Awaitable[User | None]]:
    """FastAPI dependency factory enforcing CSRF, then the central policy can()."""

    async def dependency(request: Request) -> User | None:
        user = _resolve(request)
        _verify_csrf(request, str(action))
        channel = get_channel(request)
        owner: int | None = None
        if owner_id is not None and user is not None:  # anonymous is denied by can() anyway
            try:
                owner = owner_id(request)
            except (ValueError, KeyError):
                raise ApiError(422, "validation") from None
        if can(user, action, channel, owner):
            return user
        get_services(request).audit.admin(
            actor=user,
            action=str(action),
            channel=channel,
            ip=client_ip(request),
            target={"path": request.url.path},
            result="denied",
        )
        if user is None:
            raise ApiError(401, "login_required")
        raise ApiError(403, "forbidden")

    return dependency
