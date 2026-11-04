from __future__ import annotations

import asyncio
import contextlib
import signal
import threading
from collections.abc import Iterator
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from app.services import build_services
from app.web.app_factory import create_app


def server_configs(
    local_app: FastAPI,
    external_app: FastAPI,
    local_port: int = 8700,
    external_port: int = 8701,
) -> list[uvicorn.Config]:
    # proxy_headers=False: no reverse proxy by design, so X-Forwarded-For must never
    # override request.client.host (audit ip, OTP per-IP limit).
    common = {"log_level": "info", "proxy_headers": False, "timeout_graceful_shutdown": 10}
    return [
        uvicorn.Config(local_app, host="127.0.0.1", port=local_port, **common),
        uvicorn.Config(external_app, host="0.0.0.0", port=external_port, **common),
    ]


class _Server(uvicorn.Server):
    """uvicorn.Server that leaves signal handling to serve(), so two servers share one handler."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


def request_exit(servers: list[uvicorn.Server]) -> None:
    """First signal: graceful exit. A repeated signal: force exit (mirrors uvicorn's own handler)."""
    for server in servers:
        if server.should_exit:
            server.force_exit = True
        else:
            server.should_exit = True


@contextlib.contextmanager
def _stop_on_signals(servers: list[uvicorn.Server]) -> Iterator[None]:
    """Ctrl+C / SIGTERM / SIGBREAK ask every server to exit gracefully."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    loop = asyncio.get_running_loop()

    def _handler(signum, frame) -> None:  # noqa: ARG001
        loop.call_soon_threadsafe(request_exit, servers)

    sigs = [s for s in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None)) if s]
    original = {s: signal.signal(s, _handler) for s in sigs}
    try:
        yield
    finally:
        for s, h in original.items():
            signal.signal(s, h)


async def serve(root: Path, local_port: int = 8700, external_port: int = 8701) -> None:
    services = build_services(root)
    await services.log.start()
    try:
        await services.monitor.start()
        try:
            configs = server_configs(
                create_app("local", services),
                create_app("external", services),
                local_port,
                external_port,
            )
            servers = [_Server(cfg) for cfg in configs]
            with _stop_on_signals(servers):
                await asyncio.gather(*(s.serve() for s in servers))
        finally:
            await services.monitor.stop()
    finally:
        await services.log.stop()
        services.db.close()
