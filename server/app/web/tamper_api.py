"""Recent tamper events on both channels (``view_logs``, V19): the in-memory ring of TamperMonitor."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.auth.policy import Action
from app.services import Services
from app.users.store import User
from app.web.deps import get_services, require

router = APIRouter()


@router.get("/api/tamper/recent")
async def tamper_recent(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    _user: User | None = Depends(require(Action.VIEW_LOGS)),
    services: Services = Depends(get_services),
) -> list[dict[str, Any]]:
    """Newest first."""
    return services.tamper.recent(limit)
