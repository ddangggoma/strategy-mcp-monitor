from __future__ import annotations

from fastapi import FastAPI

from app.services import Services
from app.web import local_api, shared_api
from app.web.channels import Channel
from app.web.deps import ApiError, api_error_handler


def create_app(channel: Channel, services: Services) -> FastAPI:
    app = FastAPI(title=f"MCP Monitor ({channel})", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.channel = channel
    app.state.services = services
    app.add_exception_handler(ApiError, api_error_handler)
    app.include_router(shared_api.router)
    if channel == "local":
        app.include_router(local_api.router)
    return app
