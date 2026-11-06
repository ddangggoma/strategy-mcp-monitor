"""hello → heartbeat thread → long-poll command loop. Exit codes: 0 = told to exit, 3 = the server
rejected our token, 4 = the server was unreachable for ``unreachable_exit_sec``."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from mcp_agent import VERSION, win32
from mcp_agent.client import AgentRejected, ServerClient, ServerUnavailable
from mcp_agent.config import AgentConfig
from mcp_agent.dialog import NoticeWindow

EXIT_OK = 0
EXIT_REJECTED = 3
EXIT_UNREACHABLE = 4
BACKOFF_SEC = (1, 2, 4, 8, 10)
POLL_SEC = 25.0
POLL_WHILE_SHOWN_SEC = 2.0  # check for a user-closed window at least this often
DEFAULT_HEARTBEAT_SEC = 5.0


def wants_window_events(hello: Mapping[str, Any]) -> bool:
    """HELLO ``window_events`` (Task 12): a missing key means on; False means skip the window hooks."""
    return bool(hello.get("window_events", True))


class _Unreachable(Exception):
    pass


class _Backoff:
    """1, 2, 4, 8, 10, 10 … seconds between attempts; gives up ``limit`` seconds after the first failure."""

    def __init__(self, limit: float, monotonic: Callable[[], float], sleep: Callable[[float], None]) -> None:
        self._limit, self._monotonic, self._sleep = limit, monotonic, sleep
        self._since: float | None = None
        self._failures = 0

    def failed(self) -> None:
        now = self._monotonic()
        if self._since is None:
            self._since = now
        if now - self._since >= self._limit:
            raise _Unreachable
        self._sleep(BACKOFF_SEC[min(self._failures, len(BACKOFF_SEC) - 1)])
        self._failures += 1

    def ok(self) -> None:
        self._since, self._failures = None, 0


class AgentRunner:
    def __init__(self, cfg: AgentConfig, client: ServerClient, window: NoticeWindow, *, session_id: int, pid: int,
                 monotonic: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 idle: Callable[[], float] = win32.idle_seconds,
                 on_hello: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._cfg = cfg
        self._client = client
        self._window = window
        self._session_id = session_id
        self._pid = pid
        self._idle = idle
        self._on_hello = on_hello
        self._backoff = _Backoff(cfg.unreachable_exit_sec, monotonic, sleep)
        self._stop = threading.Event()
        self._rejected = threading.Event()

    def run(self) -> int:
        heartbeat: threading.Thread | None = None
        try:
            hello = self._hello()
            if self._on_hello is not None:
                self._on_hello(hello)
            heartbeat = threading.Thread(target=self._heartbeat, args=(_heartbeat_sec(hello),), name="agent-heartbeat",
                                         daemon=True)
            heartbeat.start()
            return self._loop()
        except AgentRejected:
            return EXIT_REJECTED
        except _Unreachable:
            return EXIT_UNREACHABLE
        finally:
            self._stop.set()
            try:
                self._window.close()
            finally:
                if heartbeat is not None:
                    heartbeat.join(5)

    def _hello(self) -> dict[str, Any]:
        body = {"session_id": self._session_id, "pid": self._pid, "version": VERSION}
        while True:
            try:
                hello = self._client.post("/api/agent/hello", body)
            except ServerUnavailable:
                self._backoff.failed()
                continue
            self._backoff.ok()
            return hello or {}

    def _loop(self) -> int:
        pending: int | None = None
        while True:
            if self._rejected.is_set():
                return EXIT_REJECTED
            try:
                if pending is not None and self._window.closed_by_user():
                    self._client.post(f"/api/agent/notice/{pending}/closed")
                    pending = None
                cmd = self._client.next(POLL_WHILE_SHOWN_SEC if pending is not None else POLL_SEC)
            except ServerUnavailable:
                self._backoff.failed()
                continue
            self._backoff.ok()
            if cmd is None:
                continue
            kind = cmd.get("type")
            if kind == "show_notice":
                if pending is not None:
                    self._window.close()
                self._window.open(str(cmd["url"]), int(cmd["display_id"]))
                pending = int(cmd["display_id"])
            elif kind == "close_notice":
                if pending is not None and pending == cmd.get("display_id"):
                    self._window.close()
                    pending = None
            elif kind == "exit":
                return EXIT_OK  # run() closes the window

    def _heartbeat(self, every: float) -> None:
        while not self._stop.wait(every):
            try:
                self._client.post("/api/agent/heartbeat", {"idle_sec": int(self._idle()), "locked": None})
            except AgentRejected:
                self._rejected.set()
                return
            except ServerUnavailable:
                pass  # the command loop owns the unreachable limit
            except Exception as e:  # noqa: BLE001 - a heartbeat failure must not kill the agent
                print(f"mcp_agent: heartbeat failed: {e!r}", file=sys.stderr)


def _heartbeat_sec(hello: Mapping[str, Any]) -> float:
    try:
        sec = float(hello.get("heartbeat_sec", DEFAULT_HEARTBEAT_SEC))
    except (TypeError, ValueError):
        return DEFAULT_HEARTBEAT_SEC
    return sec if sec > 0 else DEFAULT_HEARTBEAT_SEC
