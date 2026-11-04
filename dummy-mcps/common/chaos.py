"""Fault-injection endpoints (registered only with --chaos) and the slow-response middleware."""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

SLOW_MS_MAX = 60_000
HANG_SEC_MAX = 3600


@dataclass
class ChaosState:
    slow_ms: int = 0


def _int_param(request: Request, name: str, default: int | None, lo: int, hi: int) -> int | None:
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if lo <= value <= hi else None


def chaos_routes(state: ChaosState) -> list[Route]:
    async def crash(request: Request) -> JSONResponse:
        asyncio.get_running_loop().call_later(0.1, os._exit, 1)
        return JSONResponse({"crashing": True}, status_code=202)

    async def hang(request: Request) -> JSONResponse:
        sec = _int_param(request, "sec", 30, 1, HANG_SEC_MAX)
        if sec is None:
            return JSONResponse({"error": "invalid_sec"}, status_code=422)
        # time.sleep inside the loop blocks everything: process alive, port open, no responses (UNRESPONSIVE).
        asyncio.get_running_loop().call_later(0.1, time.sleep, sec)
        return JSONResponse({"hanging_sec": sec}, status_code=202)

    async def slow(request: Request) -> JSONResponse:
        ms = _int_param(request, "ms", None, 0, SLOW_MS_MAX)
        if ms is None:
            return JSONResponse({"error": "invalid_ms"}, status_code=422)
        state.slow_ms = ms
        return JSONResponse({"slow_ms": ms})

    return [
        Route("/chaos/crash", crash, methods=["POST"]),
        Route("/chaos/hang", hang, methods=["POST"]),
        Route("/chaos/slow", slow, methods=["POST"]),
    ]


class SlowMiddleware:
    """Delays every HTTP request by state.slow_ms (the /chaos/* control routes are exempt so slow can be reset)."""

    def __init__(self, app: ASGIApp, state: ChaosState) -> None:
        self.app = app
        self.state = state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self.state.slow_ms and not scope["path"].startswith("/chaos/"):
            await asyncio.sleep(self.state.slow_ms / 1000)
        await self.app(scope, receive, send)
