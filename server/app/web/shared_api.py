from fastapi import APIRouter, Depends

from app.web.channels import Channel
from app.web.deps import get_channel

router = APIRouter()


@router.get("/api/channel")
async def channel(channel: Channel = Depends(get_channel)) -> dict[str, str]:
    return {"channel": channel}
