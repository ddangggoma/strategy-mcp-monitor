from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import uvicorn

SCRATCH = Path(os.environ["LOCALAPPDATA"]) / "mcp-monitor-install-tests"
ICACLS = str(Path(os.environ["SystemRoot"]) / "System32" / "icacls.exe")


@pytest.fixture(name="tmp_path")
def scratch_path() -> Iterator[Path]:
    """A scratch folder whose parents only SYSTEM, Administrators and this account can change.

    Import it as ``from tests.live import scratch_path`` to replace pytest's ``tmp_path`` in a module.
    The installers refuse a data root below a folder another account may delete or rename (re-review 2),
    and this PC's %TEMP% gives a sandbox's user group Modify, so pytest's own tmp_path would be refused.
    A folder under %LOCALAPPDATA% inherits only the profile's ACL. Removed after the test.
    """
    path = SCRATCH / uuid.uuid4().hex[:12]
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():  # a test failed before it unlocked its folder
        subprocess.run([ICACLS, str(path), "/reset", "/T", "/C", "/Q"], capture_output=True)
        shutil.rmtree(path, ignore_errors=True)
    try:
        SCRATCH.rmdir()
    except OSError:
        pass


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
