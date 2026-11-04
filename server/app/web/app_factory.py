from __future__ import annotations

import sys
import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from app.services import Services
from app.web import local_api, shared_api
from app.web.channels import Channel
from app.web.deps import ApiError, api_error_handler

_HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(exc.status_code, f"http_{exc.status_code}")
    return JSONResponse({"error": code}, status_code=exc.status_code, headers=exc.headers)


async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse({"error": "validation"}, status_code=422)


async def _pydantic_validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse({"error": "validation"}, status_code=422)


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    try:
        traceback.print_exception(exc, file=sys.stderr)
    except Exception:  # never fail while reporting a failure
        pass
    return JSONResponse({"error": "internal"}, status_code=500)


_LOCAL_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})


def _hostname(host_header: str) -> str:
    """Host header -> lowercase hostname without port ('[::1]:8700' -> '[::1]')."""
    host = host_header.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return host[: end + 1] if end != -1 else host
    if host.count(":") == 1:
        return host.split(":", 1)[0]
    return host


class LocalHostGuard:
    """Pure ASGI middleware (local channel only): refuse foreign Host headers (DNS rebinding)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            host = Headers(scope=scope).get("host")
            if host is None or _hostname(host) not in _LOCAL_HOSTNAMES:
                if scope["type"] == "http":
                    response = JSONResponse({"error": "bad_host"}, status_code=400)
                    await response(scope, receive, send)
                else:
                    await receive()  # websocket.connect
                    await send({"type": "websocket.close", "code": 1008})
                return
        await self.app(scope, receive, send)


def create_app(channel: Channel, services: Services) -> FastAPI:
    app = FastAPI(title=f"MCP Monitor ({channel})", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.channel = channel
    app.state.services = services
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(ValidationError, _pydantic_validation_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
    app.include_router(shared_api.router)
    if channel == "local":
        app.add_middleware(LocalHostGuard)
        app.include_router(local_api.router)
    return app
