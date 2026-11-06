from __future__ import annotations

import sys
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services import Services
from app.web import (
    local_api,
    mcp_local,
    mcp_shared,
    notice_api,
    sessions_api,
    shared_api,
    tamper_api,
)
from app.web.channels import Channel
from app.web.deps import ApiError, api_error_handler
from app.web.static import HTML_PAGES, static_router

# 3 maximal scripts (65_536 B each, JSON-escaped) plus the rest of POST /api/mcps must fit.
MAX_BODY_BYTES = 524_288

_HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 405 and request.app.state.channel == "external":
        # A wrong method on a path shared with a local-only route (POST /api/mcps, DELETE
        # /api/mcps/{id}) must look exactly like a route that does not exist: no Allow header.
        return JSONResponse({"error": "not_found"}, status_code=404)
    code = _HTTP_CODES.get(exc.status_code, f"http_{exc.status_code}")
    return JSONResponse({"error": code}, status_code=exc.status_code, headers=exc.headers)


async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
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


class BodySizeLimit:
    """Pure ASGI middleware (both channels): refuse request bodies over MAX_BODY_BYTES with 413.

    A declared Content-Length over the cap is refused at once; otherwise the bytes are
    counted as the app reads them (chunked uploads included). The 413 is sent exactly
    once and whatever the app sends afterwards is dropped.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rejected = False
        started = False

        async def reject() -> None:
            nonlocal rejected
            rejected = True
            await JSONResponse({"error": "body_too_large"}, status_code=413)(scope, receive, send)

        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isascii() and declared.isdigit():
            if int(declared) > MAX_BODY_BYTES:
                await reject()
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES and not started:
                    await reject()
                    return {"type": "http.disconnect"}
            return message

        async def limited_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except Exception:
            if not rejected:  # the app only failed because we cut its body off
                raise


def create_app(channel: Channel, services: Services, static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title=f"MCP Monitor ({channel})", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.channel = channel
    app.state.services = services
    # Starlette types a handler as taking `Exception`; it dispatches by exception class, so the narrower
    # parameter types below are safe (hence the arg-type ignores).
    app.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_handler)
    app.include_router(shared_api.router)
    app.include_router(mcp_shared.router)
    app.include_router(sessions_api.router)
    app.include_router(tamper_api.router)
    app.add_middleware(BodySizeLimit)
    if channel == "local":
        app.add_middleware(LocalHostGuard)
        app.include_router(local_api.router)
        app.include_router(mcp_local.router)
        app.include_router(notice_api.router)
    if static_dir is not None and (static_dir / HTML_PAGES["board"]).is_file():
        # After the API routers, so an API path can never be shadowed by a page. /notice is a
        # Local-channel page only.
        app.include_router(static_router(static_dir, notice=channel == "local"))
    return app
