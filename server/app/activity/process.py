"""``activity.process`` lines from WMI process start/stop events.

``ProcessComponent`` runs two watcher threads (``wmi:start``, ``wmi:stop``) that only post to the
bridge; ``ProcessActivityHandler`` writes the lines on the loop thread.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Literal

from app.activity.context import ActivityContext
from app.collect.bridge import CollectorBridge
from app.collect.manager import Collectors
from app.logstore.writer import LogSink
from app.win.wmi import ProcessEvent, ProcessEventSource, ProcessKind, ProcessWatch

_KINDS: tuple[ProcessKind, ...] = ("start", "stop")


class ProcessActivityHandler:
    """Bridge handler: resolve each event's session, remember started pids, log user sessions.

    Session 0 (services) is not logged (V13). Keys follow Appendix B: ``exe``/``cmdline`` only on
    ``start`` and ``exit_code`` only on ``stop``, each left out when None."""

    def __init__(self, context: ActivityContext, log: LogSink) -> None:
        self._context = context
        self._log = log

    def __call__(self, events: list[ProcessEvent]) -> None:
        for ev in events:
            session = ev.session_id
            if session is None:
                session = self._context.session_of(ev.pid)
            if ev.kind == "start":
                self._context.remember(ev.pid, session, ev.name, ev.at)
            if session == 0:
                continue
            fields: dict[str, Any] = {"pid": ev.pid, "ppid": ev.ppid, "name": ev.name}
            if ev.kind == "start":
                if ev.exe is not None:
                    fields["exe"] = ev.exe
                if ev.cmdline is not None:
                    fields["cmdline"] = ev.cmdline
            elif ev.exit_code is not None:
                fields["exit_code"] = ev.exit_code
            fields["source"] = ev.source
            fields.update(self._context.fields(session, user=ev.user))
            self._log.emit("activity.process", at=ev.at, event=ev.kind, **fields)


@dataclass(frozen=True)
class _WatchState:
    """Posted by a watcher thread: ``mode`` after a successful ``watch``, ``error`` on failure."""

    source: str
    mode: Literal["trace", "poll"] | None
    error: str | None


class ProcessComponent:
    name = "wmi"

    def __init__(
        self,
        source: ProcessEventSource,
        handler: ProcessActivityHandler,
        collectors: Collectors,
        *,
        retry_sec: float = 60,
        wait_ms: int = 500,
    ) -> None:
        self._source = source
        self._handler = handler
        self._collectors = collectors
        self._retry_sec = retry_sec
        self._wait_ms = wait_ms
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._errors: dict[str, str | None] = {}

    def start(self, bridge: CollectorBridge) -> None:
        if self._threads:
            raise RuntimeError("process collection already started")
        post = bridge.register(self.name, self._handle)
        self._threads = [
            threading.Thread(
                target=self._run, args=(kind, post), name=f"wmi:{kind}", daemon=True
            )
            for kind in _KINDS
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(self._wait_ms / 1000 + 2)

    # --- watcher threads (post only) ----------------------------------------------------------

    def _run(self, kind: ProcessKind, post: Any) -> None:
        source = f"wmi:{kind}"
        while not self._stop.is_set():
            try:
                watch: ProcessWatch = self._source.watch(kind)
            except Exception as exc:
                post(_WatchState(source, None, repr(exc)))
                self._stop.wait(self._retry_sec)
                continue
            failed = False
            try:
                post(_WatchState(source, watch.mode, None))
                while not self._stop.is_set():
                    ev = watch.next(self._wait_ms)
                    if ev is not None:
                        post(ev)
            except Exception as exc:
                post(_WatchState(source, None, repr(exc)))
                failed = True
            finally:
                try:
                    watch.close()
                except Exception:  # closing a broken COM query must not end the thread
                    pass
            if failed:
                self._stop.wait(self._retry_sec)

    # --- loop thread ------------------------------------------------------------------------

    def _handle(self, items: list[Any]) -> None:
        events: list[ProcessEvent] = []
        for item in items:
            if isinstance(item, _WatchState):
                self._on_state(item)
            else:
                events.append(item)
        if events:
            self._handler(events)

    def _on_state(self, state: _WatchState) -> None:
        self._errors[state.source] = state.error
        if state.error is None and state.mode is not None:
            self._collectors.report_mode(state.source, state.mode)
        failing = [err for err in self._errors.values() if err is not None]
        if failing:
            self._collectors.report(self.name, False, failing[0])
        else:
            self._collectors.report(self.name, True)
