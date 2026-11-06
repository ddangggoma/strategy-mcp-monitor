"""``GET /api/service`` (Local channel only): the Windows service's start type vs the setting."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends

from app.auth.policy import Action
from app.services import Services
from app.users.store import User
from app.web.deps import get_services, require

router = APIRouter()


@router.get("/api/service")
async def service_status(
    _actor: User | None = Depends(require(Action.EDIT_GLOBAL_SETTINGS)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    desired = services.settings.get().service_start_type  # config.db: on the loop thread
    return await asyncio.to_thread(services.start_type.status, desired)
