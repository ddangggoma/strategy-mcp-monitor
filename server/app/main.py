from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import socket
import sys
import threading
from collections.abc import Awaitable, Callable, Iterator, Sequence
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


def bind_listener(host: str, port: int, backlog: int = 2048) -> socket.socket:
    """A listening socket for ``host:port``, bound now (raises ``OSError`` when the port is taken).

    Exclusive on Windows (``SO_EXCLUSIVEADDRUSE``): no other process can bind the same address
    while we hold it, which uvicorn's own ``SO_REUSEADDR`` bind would allow (I1)."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        else:  # pragma: no cover - not Windows
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(backlog)
    except BaseException:
        sock.close()
        raise
    return sock


def bind_listeners(configs: Sequence[uvicorn.Config]) -> list[socket.socket]:
    """Both channels' sockets, bound before anything else starts: connections made meanwhile wait
    in the backlog. All or nothing."""
    sockets: list[socket.socket] = []
    try:
        for cfg in configs:
            sockets.append(bind_listener(cfg.host, cfg.port, cfg.backlog))
    except BaseException:
        for sock in sockets:
            sock.close()
        raise
    for sock in sockets:
        host, port = sock.getsockname()[:2]
        logging.getLogger("uvicorn.error").info("Uvicorn running on http://%s:%d", host, port)
    return sockets


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


class ShutdownSequence:
    """The service stop, in order: first ``before_exit`` (the collectors' stop: the agent
    supervisor tells each session agent to exit, and the agent closes its notice window), and only
    then the servers. The agents hear ``exit`` over the Local channel, so it must still answer.

    ``request()`` (loop thread): the first call starts that sequence; a repeated call goes to
    ``request_exit`` (stop serving now, then force), so an impatient second Ctrl+C still works.
    """

    def __init__(self, servers: Sequence[Any], before_exit: Callable[[], Awaitable[None]]) -> None:
        self._servers = servers
        self._before_exit = before_exit
        self._task: asyncio.Task[None] | None = None

    def request(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run(), name="shutdown")
        else:
            request_exit(self._servers)

    async def _run(self) -> None:
        try:
            await self._before_exit()
        finally:
            for server in self._servers:  # graceful only: a repeated request may already have forced
                server.should_exit = True

    async def wait(self) -> None:
        """Until a started sequence is done (re-raises its error); at once when none started."""
        if self._task is not None:
            await self._task


@contextlib.contextmanager
def _stop_on_signals(on_signal: Callable[[], None]) -> Iterator[None]:
    """Ctrl+C / SIGTERM / SIGBREAK call ``on_signal`` on the loop thread."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    loop = asyncio.get_running_loop()

    def _handler(signum, frame) -> None:  # noqa: ARG001
        loop.call_soon_threadsafe(on_signal)

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
    configs = server_configs(
        create_app("local", services, static_dir),
        create_app("external", services, static_dir),
        local_port,
        external_port,
        external_host,
    )
    await services.log.start()
    try:
        # I1: own both ports before the collectors start, so a session agent launched by the
        # supervisor never finds the Local port unbound (or bound by another process).
        sockets = bind_listeners(configs)
        try:
            await services.monitor.start()
            try:
                await services.collectors.start()
                shutdown: ShutdownSequence | None = None
                try:
                    servers = [_Server(cfg) for cfg in configs]
                    shutdown = ShutdownSequence(servers, services.collectors.stop)
                    with _stop_on_signals(shutdown.request):
                        await asyncio.gather(
                            *(s.serve(sockets=[sock]) for s, sock in zip(servers, sockets, strict=True))
                        )
                finally:
                    try:
                        if shutdown is not None:
                            await shutdown.wait()
                    finally:
                        await services.collectors.stop()  # a no-op after the sequence stopped them
            finally:
                await services.monitor.stop()
        finally:
            for sock in sockets:
                sock.close()
    finally:
        await services.log.stop()
        services.db.close()
