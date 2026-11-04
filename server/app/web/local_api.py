"""Routes served only on the local channel. Never registered on the external app."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services import Services
from app.users.store import BootstrapDoneError, InvalidEmailError
from app.web.channels import Channel
from app.web.deps import ApiError, client_ip, get_channel, get_services, user_json

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
