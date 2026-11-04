from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.auth.otp import OtpRateLimitError
from app.services import Services
from app.users.store import InvalidEmailError, User, normalize_email
from app.web.channels import Channel
from app.web.deps import (
    SESSION_COOKIE,
    ApiError,
    check_csrf,
    client_ip,
    current_user,
    get_channel,
    get_services,
    user_json,
)

router = APIRouter()

_MAX_AUDIT_EMAIL = 320


class OtpRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=320)


class OtpVerifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=320)
    code: str = Field(max_length=16)


def _audit_email(raw: str) -> str:
    """Normalized email for the audit log, or the (length-capped) raw input if it is invalid."""
    try:
        return normalize_email(raw)
    except InvalidEmailError:
        return raw[:_MAX_AUDIT_EMAIL]


def _live_sid(request: Request) -> str | None:
    """The cookie's session id, only if it resolved to a live session on THIS channel.

    Never revoke a raw cookie value: a session of the other channel must stay untouched.
    Requires a prior current_user dependency (it fills request.state.auth_session).
    """
    if getattr(request.state, "auth_session", None) is None:
        return None
    return request.cookies.get(SESSION_COOKIE)


def _cookie_args(request: Request) -> dict[str, Any]:
    return {
        "httponly": True,
        "samesite": "strict",
        "path": "/",
        "secure": request.url.scheme == "https",
    }


@router.get("/api/channel")
async def channel(channel: Channel = Depends(get_channel)) -> dict[str, str]:
    return {"channel": channel}


@router.post("/api/auth/otp/request", status_code=202)
async def otp_request(
    body: OtpRequestBody,
    request: Request,
    services: Services = Depends(get_services),
    channel: Channel = Depends(get_channel),
) -> dict[str, object]:
    ip = client_ip(request)
    email = _audit_email(body.email)
    user_agent = request.headers.get("user-agent")
    ok = False
    rate_limited: OtpRateLimitError | None = None
    try:
        services.otp.request(body.email, ip or "unknown")
        ok = True
    except InvalidEmailError:
        raise ApiError(422, "invalid_email") from None
    except OtpRateLimitError as exc:
        rate_limited = exc
    finally:
        if rate_limited is not None:  # only the first 429 per (event, ip) per window is audited
            services.audit.auth_rate_limited(
                event="otp_request",
                email=email,
                channel=channel,
                ip=ip,
                user_agent=user_agent,
                now=services.clock.now(),
                scope=rate_limited.scope,
            )
        else:
            services.audit.auth(
                event="otp_request",
                email=email,
                channel=channel,
                ip=ip,
                user_agent=user_agent,
                ok=ok,
            )
    if rate_limited is not None:
        raise ApiError(429, "rate_limited", {"Retry-After": str(rate_limited.retry_after)})
    return {}


@router.post("/api/auth/otp/verify")
async def otp_verify(
    body: OtpVerifyBody,
    request: Request,
    response: Response,
    services: Services = Depends(get_services),
    channel: Channel = Depends(get_channel),
    _current: User | None = Depends(current_user),  # resolves this channel's session first
) -> dict[str, object]:
    ip = client_ip(request)
    user_agent = request.headers.get("user-agent")

    def audit_login(email: str, ok: bool) -> None:
        services.audit.auth(
            event="login", email=email, channel=channel, ip=ip, user_agent=user_agent, ok=ok
        )

    try:
        user = services.otp.verify(body.email, body.code, ip or "unknown")
    except OtpRateLimitError as exc:
        services.audit.auth_rate_limited(
            event="login",
            email=_audit_email(body.email),
            channel=channel,
            ip=ip,
            user_agent=user_agent,
            now=services.clock.now(),
            scope=exc.scope,
        )
        raise ApiError(429, "rate_limited", {"Retry-After": str(exc.retry_after)}) from None
    if user is None:
        audit_login(_audit_email(body.email), False)
        raise ApiError(401, "login_required")
    try:
        old_sid = _live_sid(request)
        if old_sid:  # session fixation: never leave a pre-login session of this channel alive
            services.sessions.revoke(old_sid)
        services.users.touch_login(user.id)
        sid, csrf_token = services.sessions.create(user.id, channel, ip, user_agent)
    except Exception:
        audit_login(user.email, False)
        raise
    audit_login(user.email, True)
    response.set_cookie(SESSION_COOKIE, sid, **_cookie_args(request))
    return {"user": user_json(user), "csrf_token": csrf_token}


@router.post("/api/auth/logout", status_code=204, dependencies=[Depends(check_csrf)])
async def logout(
    request: Request,
    user: User | None = Depends(current_user),
    services: Services = Depends(get_services),
    channel: Channel = Depends(get_channel),
) -> Response:
    sid = _live_sid(request)
    if sid:
        services.sessions.revoke(sid)
    if user is not None:
        services.audit.auth(
            event="logout",
            email=user.email,
            channel=channel,
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
            ok=True,
        )
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, **_cookie_args(request))
    return response


@router.get("/api/auth/me")
async def me(
    request: Request,
    user: User | None = Depends(current_user),
    channel: Channel = Depends(get_channel),
) -> dict[str, object]:
    session = getattr(request.state, "auth_session", None) if user is not None else None
    return {
        "user": user_json(user) if user is not None else None,
        "channel": channel,
        # lets the SPA recover its CSRF token after a page reload (same-origin, session-bound)
        "csrf_token": session.csrf_token if session is not None else None,
    }
