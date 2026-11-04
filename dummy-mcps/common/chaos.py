"""Fault-injection endpoints (registered only with --chaos) and the slow-response middleware."""
from __future__ import annotations

import asyncio
import functools
import os
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

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


_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})


def _host_name(host_header: str) -> str:
    """Hostname part of a Host header value (port stripped; bracketed IPv6 kept bracketed)."""
    host = host_header.strip().lower()
    if host.startswith("["):
        return host[: host.find("]") + 1] if "]" in host else host
    return host.partition(":")[0]


def _is_local_request(request: Request) -> bool:
    """False for a foreign Host (DNS rebinding) or any non-local Origin (cross-origin browser request)."""
    if _host_name(request.headers.get("host", "")) not in _LOCAL_HOSTS:
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return True
    parts = urlsplit(origin)
    try:
        hostname = parts.hostname
    except ValueError:
        return False
    host = f"[{hostname}]" if hostname and ":" in hostname else hostname
    return parts.scheme in ("http", "https") and host in _LOCAL_HOSTS


def _local_only(handler):
    @functools.wraps(handler)
    async def guarded(request: Request) -> JSONResponse:
        if not _is_local_request(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return await handler(request)
    return guarded


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
        Route("/chaos/crash", _local_only(crash), methods=["POST"]),
        Route("/chaos/hang", _local_only(hang), methods=["POST"]),
        Route("/chaos/slow", _local_only(slow), methods=["POST"]),
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
