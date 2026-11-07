"""Shared test helpers (also used by Plan 2 Task 4)."""
from __future__ import annotations

import json
import socket
import time
from pathlib import Path

import httpx
import psutil

ROOT: Path = Path(__file__).resolve().parent.parent  # dummy-mcps/

_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def listener_pid(port: int) -> int | None:
    for c in psutil.net_connections("tcp"):
        if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port:
            return c.pid
    return None


def wait_listening(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"port {port} not listening after {timeout}s")
            time.sleep(0.1)


def kill_tree(proc, timeout: float = 10.0) -> None:
    """Kill a Popen and every descendant (the venv launcher spawns the real interpreter), then wait."""
    try:
        parent = psutil.Process(proc.pid)
        victims = parent.children(recursive=True) + [parent]
    except psutil.NoSuchProcess:
        victims = []
    for v in victims:
        try:
            v.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(victims, timeout=timeout)
    proc.wait(timeout)


def wait_port_free(port: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while listener_pid(port) is not None:
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


def rpc(port: int, method: str, params: dict | None = None, *, session: str | None = None,
        id: int | None = 1, timeout: float = 3.0) -> tuple[dict | None, httpx.Headers]:
    body: dict = {"jsonrpc": "2.0", "method": method}
    if id is not None:
        body["id"] = id
    if params is not None:
        body["params"] = params
    headers = dict(_HEADERS)
    if session:
        headers["Mcp-Session-Id"] = session
        headers["Mcp-Protocol-Version"] = "2025-06-18"
    r = httpx.post(f"http://127.0.0.1:{port}/mcp", json=body, headers=headers, timeout=timeout)
    if id is None:
        return None, r.headers
    if r.headers.get("content-type", "").startswith("text/event-stream"):
        for line in r.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip()), r.headers
        raise AssertionError(f"no data line in SSE body: {r.text!r}")
    return r.json(), r.headers


def open_session(port: int) -> str | None:
    _, h = rpc(port, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "t", "version": "0"}})
    sid = h.get("mcp-session-id")
    rpc(port, "notifications/initialized", session=sid, id=None)
    return sid
