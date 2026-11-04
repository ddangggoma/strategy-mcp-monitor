"""Routes served only on the local channel. Never registered on the external app."""
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth.policy import Action
from app.clock import to_kst_iso
from app.services import Services
from app.users.store import (
    BootstrapDoneError,
    InvalidEmailError,
    LastAdminError,
    User,
    UserExistsError,
    UserNotFoundError,
)
from app.web.channels import Channel
from app.web.deps import ApiError, client_ip, get_channel, get_services, require, user_json

router = APIRouter()


class BootstrapBody(BaseModel):
    email: str
    name: str


@router.get("/api/bootstrap")
async def bootstrap_status(services: Services = Depends(get_services)) -> dict[str, bool]:
    return {"needed": services.users.count() == 0}


@router.post("/api/bootstrap", status_code=201)
async def bootstrap(
    body: BootstrapBody,
    request: Request,
    services: Services = Depends(get_services),
    channel: Channel = Depends(get_channel),
) -> JSONResponse:
    ip = client_ip(request)
    try:
        user = services.users.create_first_admin(body.email, body.name)
    except InvalidEmailError:
        raise ApiError(422, "invalid_email") from None
    except ValueError:  # empty name
        raise ApiError(422, "validation") from None
    except BootstrapDoneError:
        services.audit.admin(
            actor=None, action="bootstrap", channel=channel, ip=ip, target={}, result="denied"
        )
        raise ApiError(409, "bootstrap_done") from None
    services.audit.admin(
        actor=user,
        action="bootstrap",
        channel=channel,
        ip=ip,
        target={"user_id": user.id},
        result="ok",
    )
    return JSONResponse(user_json(user), status_code=201)


class CreateUserBody(BaseModel):
    email: str
    name: str
    role: Literal["developer", "admin"]


class UpdateUserBody(BaseModel):
    name: str | None = None
    role: Literal["developer", "admin"] | None = None
    active: bool | None = None


def _admin_user_json(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "active": user.active,
        "created_at": to_kst_iso(user.created_at),
        "last_login_at": to_kst_iso(user.last_login_at) if user.last_login_at else None,
    }


@router.get("/api/users")
async def list_users(
    _actor: User | None = Depends(require(Action.MANAGE_USERS)),
    services: Services = Depends(get_services),
) -> list[dict[str, object]]:
    return [_admin_user_json(u) for u in services.users.list()]


@router.post("/api/users", status_code=201)
async def create_user(
    body: CreateUserBody,
    request: Request,
    actor: User | None = Depends(require(Action.MANAGE_USERS)),
    services: Services = Depends(get_services),
    channel: Channel = Depends(get_channel),
) -> JSONResponse:
    assert actor is not None  # require() denies anonymous
    ip = client_ip(request)
    try:
        user = services.users.create(body.email, body.name, body.role, created_by=actor.id)
    except UserExistsError:
        status, code = 409, "user_exists"
    except InvalidEmailError:  # must precede ValueError: it is a subclass
        status, code = 422, "invalid_email"
    except ValueError:  # empty name
        status, code = 422, "validation"
    else:
        services.audit.admin(
            actor=actor,
            action="user_create",
            channel=channel,
            ip=ip,
            target={"user_id": user.id, "email": user.email, "role": user.role},
            result="ok",
        )
        return JSONResponse(_admin_user_json(user), status_code=201)
    services.audit.admin(
        actor=actor,
        action="user_create",
        channel=channel,
        ip=ip,
        target={"email": body.email, "role": body.role, "error": code},
        result="error",
    )
    raise ApiError(status, code)


@router.patch("/api/users/{user_id}")
async def update_user(
    user_id: int,
    body: UpdateUserBody,
    request: Request,
    actor: User | None = Depends(require(Action.MANAGE_USERS)),
    services: Services = Depends(get_services),
    channel: Channel = Depends(get_channel),
) -> dict[str, object]:
    ip = client_ip(request)
    target: dict[str, object] = {"user_id": user_id}
    changes: dict[str, list[object]] = {}
    user = services.users.get(user_id)
    status, code = 0, ""
    try:
        if user is None:
            raise UserNotFoundError(user_id)
        target["email"] = user.email
        if body.name is not None:
            updated = services.users.set_name(user_id, body.name)
            if updated.name != user.name:
                changes["name"] = [user.name, updated.name]
            user = updated
        if body.role is not None and body.role != user.role:
            updated = services.users.set_role(user_id, body.role)
            changes["role"] = [user.role, updated.role]
            user = updated
        if body.active is not None and body.active != user.active:
            updated = services.users.set_active(user_id, body.active)
            changes["active"] = [user.active, updated.active]
            user = updated
    except UserNotFoundError:
        status, code = 404, "not_found"
    except LastAdminError:
        status, code = 409, "last_admin"
    except ValueError:  # empty name
        status, code = 422, "validation"
    # Earlier fields may already have been applied before a later one failed:
    # revoke and record whatever really changed.
    if "role" in changes or "active" in changes:
        services.sessions.revoke_user(user_id)
    if changes:
        target["changes"] = changes
    if code:
        target["error"] = code
        services.audit.admin(
            actor=actor, action="user_update", channel=channel, ip=ip, target=target, result="error"
        )
        raise ApiError(status, code)
    if changes:
        services.audit.admin(
            actor=actor, action="user_update", channel=channel, ip=ip, target=target, result="ok"
        )
    assert user is not None
    return _admin_user_json(user)
