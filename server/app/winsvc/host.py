"""The service's work, free of pywin32 so it runs (and is tested) as a plain object."""

from __future__ import annotations

import os
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from app.__main__ import parse_args, run_server
from app.main import ServeControl
from app.winsvc import (
    DESCRIPTION,
    DISPLAY_NAME,
    PRESHUTDOWN_TIMEOUT_MS,
    SERVICE_NAME,
    STOP_DEADLINE_SEC,
    STOP_HEARTBEAT_SEC,
    STOP_WAIT_HINT_MS,
)
from app.winsvc.start_type import ServiceConfigurator

__all__ = [
    "DESCRIPTION", "DISPLAY_NAME", "PRESHUTDOWN_TIMEOUT_MS", "SERVICE_NAME", "STOP_DEADLINE_SEC",
    "STOP_HEARTBEAT_SEC", "STOP_WAIT_HINT_MS", "ServiceHost", "StopHeartbeat", "run_for_scm",
]


class ServiceHost:
    """Runs the server for the SCM: ``run()`` blocks on the service thread; ``stop()`` and
    ``session_change()`` come from the SCM's control-handler thread. ``configurator`` replaces the
    real SCM for the start-type reconcile (tests: never the installed service)."""

    def __init__(
        self,
        argv: list[str],
        *,
        chdir: Callable[[Path], None] = os.chdir,
        configurator: ServiceConfigurator | None = None,
    ) -> None:
        self.argv = list(argv)
        self.control = ServeControl(as_service=True, configurator=configurator)
        self._chdir = chdir

    def run(self) -> int:
        try:
            ns = parse_args(self.argv)
        except SystemExit as exc:  # argparse already wrote the error to stderr
            return exc.code if isinstance(exc.code, int) else 2
        self._chdir(ns.root.resolve())  # a service starts in System32 (W22)
        return run_server(ns, self.control)

    def stop(self) -> None:
        self.control.request_stop()

    def session_change(self, event_type: int, session_id: int) -> None:  # noqa: ARG002
        """``SERVICE_CONTROL_SESSIONCHANGE``: poll the RDP sessions now (not at the next tick)."""
        self.control.nudge_sessions()


def run_for_scm(run: Callable[[], int], stop_requested: threading.Event, log_error: Callable[[str], None]) -> int | None:
    """Run the service's work and decide how the process ends (W22, plan review I4).

    ``None``: report ``SERVICE_STOPPED`` (return normally) — the SCM asked for the stop, so even a
    shutdown that failed must not look like a crash: with ``failureflag 1`` the SCM restarts a service
    that ends without STOPPED *or* reports STOPPED with a non-zero exit code, so the code goes to the
    event log instead. An ``int``: the code to leave with without reporting STOPPED, so the SCM's
    recovery actions start the service again (it ended on its own).
    """
    try:
        code = run()
    except BaseException:
        log_error(traceback.format_exc())
        code = 1
    if stop_requested.is_set():
        if code != 0:
            log_error(f"mcp-monitor stopped on request with errors (code {code})")
        return None
    log_error(f"mcp-monitor exited with code {code}")
    return code or 1


class StopHeartbeat:
    """While a requested stop runs, keep the SCM informed (plan review I5): ``report()`` (a
    ``SERVICE_STOP_PENDING`` with the next checkpoint) every ``interval`` seconds until ``done`` is
    set. Past ``deadline`` seconds ``give_up()`` runs once instead: the stop sequence is capped."""

    def __init__(
        self,
        report: Callable[[], None],
        done: threading.Event,
        give_up: Callable[[], None],
        *,
        interval: float = STOP_HEARTBEAT_SEC,
        deadline: float = STOP_DEADLINE_SEC,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._report = report
        self._done = done
        self._give_up = give_up
        self._interval = interval
        self._deadline = deadline
        self._clock = clock

    def run(self) -> None:
        started = self._clock()
        while not self._done.wait(self._interval):
            if self._clock() - started >= self._deadline:
                self._give_up()
                return
            self._report()

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.run, name="stop-heartbeat", daemon=True)
        thread.start()
        return thread
