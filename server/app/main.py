from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI

from app.collect.config import CollectorConfig
from app.services import build_services
from app.web.app_factory import create_app


def server_configs(
    local_app: FastAPI,
    external_app: FastAPI,
    local_port: int = 8700,
    external_port: int = 8701,
    external_host: str = "0.0.0.0",
) -> list[uvicorn.Config]:
    # proxy_headers=False: no reverse proxy by design, so X-Forwarded-For must never
    # override request.client.host (audit ip, OTP per-IP limit).
    common: dict[str, Any] = {"log_level": "info", "proxy_headers": False, "timeout_graceful_shutdown": 10}
    return [
        uvicorn.Config(local_app, host="127.0.0.1", port=local_port, **common),
        uvicorn.Config(external_app, host=external_host, port=external_port, **common),
    ]


class _Server(uvicorn.Server):
    """uvicorn.Server that leaves signal handling to serve(), so two servers share one handler."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


def request_exit(servers: Sequence[uvicorn.Server]) -> None:
    """First signal: graceful exit. A repeated signal: force exit (mirrors uvicorn's own handler)."""
    for server in servers:
        if server.should_exit:
            server.force_exit = True
        else:
            server.should_exit = True


@contextlib.contextmanager
def _stop_on_signals(servers: Sequence[uvicorn.Server]) -> Iterator[None]:
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


async def serve(
    root: Path,
    local_port: int = 8700,
    external_port: int = 8701,
    *,
    external_host: str = "0.0.0.0",
    static_dir: Path | None = None,
    dev_otp_code: str | None = None,
    collectors: CollectorConfig | None = None,
) -> None:
    if dev_otp_code is not None:
        print("WARNING: dev OTP code enabled", file=sys.stderr, flush=True)
    if static_dir is not None and not (static_dir / "board.html").is_file():
        print(f"WARNING: no built web app in {static_dir}; serving the API only", file=sys.stderr, flush=True)
    services = build_services(root, dev_fixed_code=dev_otp_code, collectors=collectors)
    local_url = f"http://127.0.0.1:{local_port}"
    services.agents.configure(local_url)
    if services.agent_supervisor is not None:
        services.agent_supervisor.configure(local_url)
    await services.log.start()
    try:
        await services.monitor.start()
        try:
            await services.collectors.start()
            try:
                configs = server_configs(
                    create_app("local", services, static_dir),
                    create_app("external", services, static_dir),
                    local_port,
                    external_port,
                    external_host,
                )
                servers = [_Server(cfg) for cfg in configs]
                with _stop_on_signals(servers):
                    await asyncio.gather(*(s.serve() for s in servers))
            finally:
                await services.collectors.stop()
        finally:
            await services.monitor.stop()
    finally:
        await services.log.stop()
        services.db.close()
