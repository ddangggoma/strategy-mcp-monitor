"""Routes served only on the local channel. Never registered on the external app."""
from fastapi import APIRouter, Depends

from app.services import Services
from app.web.deps import get_services

router = APIRouter()


@router.get("/api/bootstrap")
async def bootstrap_status(services: Services = Depends(get_services)) -> dict[str, bool]:
    return {"needed": services.users.count() == 0}
