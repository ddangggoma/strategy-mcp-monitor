"""A stand-in for the monitor's Local agent API (``/api/agent/*``), on 127.0.0.1 and port 0."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

# The hub's HELLO (server/app/activity/agent_hub.py), "window_events" included (Task 12 carry).
DEFAULT_HELLO = {"heartbeat_sec": 5, "events_max": 200, "idle_threshold_sec": 300, "window_events": True}


class FakeServer:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, Any, dict[str, str]]] = []
        self.commands: deque[dict[str, Any]] = deque()
        self.status_for: dict[str, int] = {}
        self.hello_body: dict[str, Any] = dict(DEFAULT_HELLO)
        self._lock = threading.Lock()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(self))
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, args=(0.05,), name="fake-server", daemon=True)

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(5)

    def _record(self, method: str, path: str, body: Any, headers: dict[str, str]) -> None:
        with self._lock:
            self.requests.append((method, path, body, headers))

    def _next_command(self) -> dict[str, Any] | None:
        with self._lock:
            return self.commands.popleft() if self.commands else None


def _make_handler(fake: FakeServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # keep test output quiet
            pass

        def _send(self, status: int, payload: Any = None) -> None:
            data = b"" if payload is None else json.dumps(payload).encode("utf-8")
            self.send_response(status)
            if data:
                self.send_header("Content-Type", "application/json")
            if status != 204:
                self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if data:
                self.wfile.write(data)

        def _handle(self, method: str) -> None:
            path = urlsplit(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw.decode("utf-8")) if raw else None
            # urllib sends "X-agent-token"; title-case the names so tests read them as written.
            headers = {k.title(): v for k, v in self.headers.items()}
            fake._record(method, path, body, headers)
            forced = fake.status_for.get(path)
            if forced is not None:
                self._send(forced, {"error": "forced"} if forced >= 400 else None)
            elif method == "GET" and path == "/api/agent/next":
                cmd = fake._next_command()
                if cmd is None:
                    time.sleep(0.05)
                    self._send(204)
                else:
                    self._send(200, cmd)
            elif method == "POST" and path == "/api/agent/hello":
                self._send(200, fake.hello_body)
            elif method == "POST":
                self._send(204)
            else:
                self._send(404, {"error": "not_found"})

        def do_GET(self) -> None:
            self._handle("GET")

        def do_POST(self) -> None:
            self._handle("POST")

    return Handler
