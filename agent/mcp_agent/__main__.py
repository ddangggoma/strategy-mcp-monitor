"""``python -m mcp_agent --server http://127.0.0.1:8700 [--dialog edge|print] ...``

The per-launch token comes in ``MCPMON_AGENT_TOKEN`` and is removed from the environment at once.
"""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable
from typing import Any

from mcp_agent import win32
from mcp_agent.client import ServerClient
from mcp_agent.coalesce import RawWinEvent, WindowEventCoalescer
from mcp_agent.config import parse_args
from mcp_agent.dialog import EdgeWindow, NoticeWindow, PrintWindow, find_edge
from mcp_agent.hooks import WinEventHookThread
from mcp_agent.idle import IdleTracker
from mcp_agent.pump import EventPump
from mcp_agent.runner import AgentRunner, wants_window_events
from mcp_agent.sender import EventSender

DEFAULT_EVENTS_MAX = 200
DEFAULT_IDLE_THRESHOLD_SEC = 300.0


class WindowActivity:
    """Window hooks + event pump, started by ``on_hello`` when the server wants window events."""

    def __init__(self, client: ServerClient, *,
                 hook_factory: Callable[[Callable[[RawWinEvent], None]], Any] = WinEventHookThread,
                 idle_seconds: Callable[[], float] = win32.idle_seconds) -> None:
        self._client = client
        self._hook_factory = hook_factory
        self._idle_seconds = idle_seconds
        self._stop = threading.Event()
        self._hooks: Any = None
        self._thread: threading.Thread | None = None
        self._sender: EventSender | None = None
        self.pump: EventPump | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def on_hello(self, hello: dict[str, Any]) -> None:
        if not wants_window_events(hello):
            return  # e.g. ``--activity off`` on the server (F13)
        self._sender = EventSender(self._client, events_max=_number(hello, "events_max", DEFAULT_EVENTS_MAX, int))
        idle = IdleTracker(_number(hello, "idle_threshold_sec", DEFAULT_IDLE_THRESHOLD_SEC, float))
        self.pump = EventPump(WindowEventCoalescer(), self._sender, idle, idle_seconds=self._idle_seconds)
        self._hooks = self._hook_factory(self.pump.on_raw)
        self._hooks.start()
        self._thread = threading.Thread(target=self.pump.run, args=(self._stop,), name="agent-events", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the hooks and the pump, then deliver what is left once."""
        if self._hooks is not None:
            self._hooks.stop()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(5)
        if self._sender is not None:
            try:
                self._sender.flush()
            except Exception as e:  # noqa: BLE001 - shutting down; a rejected token or outage loses the rest
                print(f"mcp_agent: final event flush failed: {e!r}", file=sys.stderr)


def _number[T: (int, float)](hello: dict[str, Any], key: str, default: T, kind: type[T]) -> T:
    try:
        value = kind(hello.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def main(argv: list[str] | None = None) -> int:
    cfg = parse_args(sys.argv[1:] if argv is None else argv, os.environ)
    client = ServerClient(cfg.server, cfg.token)
    window: NoticeWindow
    if cfg.dialog == "print":
        assert cfg.url_file is not None  # parse_args requires it
        window = PrintWindow(cfg.url_file)
    else:
        window = EdgeWindow(cfg.edge_path or find_edge(), cfg.profile_dir)
    activity = WindowActivity(client)
    try:
        return AgentRunner(cfg, client, window, session_id=win32.current_session_id(), pid=os.getpid(),
                           on_hello=activity.on_hello).run()
    finally:
        activity.stop()


if __name__ == "__main__":
    sys.exit(main())
