"""The service's work, free of pywin32 so it runs (and is tested) as a plain object."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from app.__main__ import parse_args, run_server
from app.main import ServeControl
from app.winsvc import DESCRIPTION, DISPLAY_NAME, SERVICE_NAME, STOP_WAIT_HINT_MS

__all__ = ["DESCRIPTION", "DISPLAY_NAME", "SERVICE_NAME", "STOP_WAIT_HINT_MS", "ServiceHost"]


class ServiceHost:
    """Runs the server for the SCM: ``run()`` blocks on the service thread; ``stop()`` and
    ``session_change()`` come from the SCM's control-handler thread."""

    def __init__(self, argv: list[str], *, chdir: Callable[[Path], None] = os.chdir) -> None:
        self.argv = list(argv)
        self.control = ServeControl(as_service=True)
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
