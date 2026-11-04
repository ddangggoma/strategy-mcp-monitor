from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

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
    email: str


class OtpVerifyBody(BaseModel):
    email: str
    code: str


def _audit_email(raw: str) -> str:
    """Normalized email for the audit log, or the (length-capped) raw input if it is invalid."""
    try:
        return normalize_email(raw)
    except InvalidEmailError:
        return raw[:_MAX_AUDIT_EMAIL]


def _cookie_args(request: Request) -> dict[str, object]:
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
    ok = False
    try:
        services.otp.request(body.email, ip or "unknown")
        ok = True
    except InvalidEmailError:
        raise ApiError(422, "invalid_email") from None
    except OtpRateLimitError as exc:
        raise ApiError(429, "rate_limited", {"Retry-After": str(exc.retry_after)}) from None
    finally:
        services.audit.auth(
            event="otp_request",
            email=email,
            channel=channel,
            ip=ip,
            user_agent=request.headers.get("user-agent"),
            ok=ok,
        )
    return {}


@router.post("/api/auth/otp/verify")
async def otp_verify(
    body: OtpVerifyBody,
    request: Request,
    response: Response,
    services: Services = Depends(get_services),
    channel: Channel = Depends(get_channel),
) -> dict[str, object]:
    ip = client_ip(request)
    user_agent = request.headers.get("user-agent")
    user = services.otp.verify(body.email, body.code)
    services.audit.auth(
        event="login",
        email=user.email if user is not None else _audit_email(body.email),
        channel=channel,
        ip=ip,
        user_agent=user_agent,
        ok=user is not None,
    )
    if user is None:
        raise ApiError(401, "login_required")
    old_sid = request.cookies.get(SESSION_COOKIE)
    if old_sid:  # session fixation: never reuse or leave alive a pre-login session
        services.sessions.revoke(old_sid)
    services.users.touch_login(user.id)
    sid, csrf_token = services.sessions.create(user.id, channel, ip, user_agent)
    response.set_cookie(SESSION_COOKIE, sid, **_cookie_args(request))
    return {"user": user_json(user), "csrf_token": csrf_token}


@router.post("/api/auth/logout", status_code=204, dependencies=[Depends(check_csrf)])
async def logout(
    request: Request,
    user: User | None = Depends(current_user),
    services: Services = Depends(get_services),
    channel: Channel = Depends(get_channel),
) -> Response:
    sid = request.cookies.get(SESSION_COOKIE)
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
    user: User | None = Depends(current_user), channel: Channel = Depends(get_channel)
) -> dict[str, object]:
    return {"user": user_json(user) if user is not None else None, "channel": channel}
