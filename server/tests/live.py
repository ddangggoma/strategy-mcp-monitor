from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def live_app(app) -> AsyncIterator[str]:
    """Serve an ASGI app on a loopback port inside the running event loop; yields its base URL.

    The listening socket is bound up front (port 0), so there is no free-port race.
    """
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="warning", lifespan="off", timeout_graceful_shutdown=1)
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        while not server.started:
            if task.done():
                await task  # surfaces the startup failure
                raise RuntimeError("uvicorn exited before it started")
            await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        try:
            await task
        finally:
            sock.close()
