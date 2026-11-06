"""The SCM side of ``python -m app service`` (pywin32; Windows only).

PyInstaller needs ``win32timezone`` as a hidden import for this module (Task 13).
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any, ClassVar

import pywintypes
import servicemanager
import win32service
import win32serviceutil

from app.winsvc import (
    DESCRIPTION,
    DISPLAY_NAME,
    PRESHUTDOWN_TIMEOUT_MS,
    SERVICE_NAME,
    STOP_DEADLINE_SEC,
    STOP_WAIT_HINT_MS,
)
from app.winsvc.host import ServiceHost, StopHeartbeat, run_for_scm
from app.winsvc.start_type import ScmConfigurator

_ERROR_FAILED_SERVICE_CONTROLLER_CONNECT = 1063


# Module-level so tests replace them (never the event log, the SCM or a real exit there).
def _log_error(msg: str) -> None:
    servicemanager.LogErrorMsg(msg)


def _log_warning(msg: str) -> None:
    servicemanager.LogWarningMsg(msg)


def _set_preshutdown_timeout() -> None:
    ScmConfigurator().set_preshutdown_timeout(PRESHUTDOWN_TIMEOUT_MS)


_exit = os._exit


class McpMonitorService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = DISPLAY_NAME
    _svc_description_ = DESCRIPTION
    host_argv: ClassVar[list[str]] = []

    def __init__(self, args: Any) -> None:
        super().__init__(args)
        self._setup(ServiceHost(self.host_argv))

    def _setup(self, host: ServiceHost) -> None:
        self.host = host
        self._stop_requested = threading.Event()
        self._run_done = threading.Event()
        self._status_lock = threading.Lock()  # the service thread and the heartbeat both report

    def _report(self, status: int, **kw: Any) -> None:
        with self._status_lock:
            self.ReportServiceStatus(status, **kw)

    def GetAcceptedControls(self) -> int:  # noqa: N802 - pywin32 API
        accepted: int = super().GetAcceptedControls()
        return (accepted | win32service.SERVICE_ACCEPT_SHUTDOWN | win32service.SERVICE_ACCEPT_SESSIONCHANGE
                | win32service.SERVICE_ACCEPT_PRESHUTDOWN)

    def _request_stop(self) -> None:
        if self._stop_requested.is_set():
            return  # SHUTDOWN after PRESHUTDOWN, or a second sc stop: one stop sequence
        self._stop_requested.set()
        self._report(win32service.SERVICE_STOP_PENDING, waitHint=STOP_WAIT_HINT_MS)
        StopHeartbeat(
            lambda: self._report(win32service.SERVICE_STOP_PENDING, waitHint=STOP_WAIT_HINT_MS),
            self._run_done,
            self._give_up,
        ).start()
        self.host.stop()

    def _give_up(self) -> None:
        """The stop sequence ran past ``STOP_DEADLINE_SEC``: report STOPPED (a requested stop, so no
        recovery restart) and leave."""
        _log_error(f"mcp-monitor did not stop within {STOP_DEADLINE_SEC:.0f} s; leaving now")
        self._report(win32service.SERVICE_STOPPED)
        _exit(0)

    def SvcStop(self) -> None:  # noqa: N802 - pywin32 API
        self._request_stop()

    def SvcShutdown(self) -> None:  # noqa: N802 - pywin32 API
        self._request_stop()

    def SvcOtherEx(self, control: int, event_type: int, data: Any) -> None:  # noqa: N802 - pywin32 API
        if control == win32service.SERVICE_CONTROL_SESSIONCHANGE:
            self.host.session_change(event_type, data[0])
        elif control == win32service.SERVICE_CONTROL_PRESHUTDOWN:
            self._request_stop()

    def SvcRun(self) -> None:  # noqa: N802 - pywin32 API
        # The framework's SvcRun reports STOP_PENDING after SvcDoRun; the C side reports STOPPED
        # when this returns. Nothing in between: the heartbeat may still be reporting.
        self.SvcDoRun()

    def SvcDoRun(self) -> None:  # noqa: N802 - pywin32 API
        self._report(win32service.SERVICE_RUNNING)
        try:
            _set_preshutdown_timeout()  # the service may change its own config (LocalSystem)
        except (OSError, LookupError) as exc:
            _log_warning(f"mcp-monitor could not set its preshutdown timeout: {exc}")
        try:
            code = run_for_scm(self.host.run, self._stop_requested, _log_error)
        finally:
            self._run_done.set()
        if code is not None:
            _exit(code)  # ended on its own: no STOPPED, so the SCM's recovery restarts it (W22)


def dispatch(argv: list[str]) -> int:
    """``python -m app service <server args>``: hand this process to the SCM."""
    McpMonitorService.host_argv = list(argv)
    try:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(McpMonitorService)
        servicemanager.StartServiceCtrlDispatcher()
    except pywintypes.error as exc:
        if exc.winerror != _ERROR_FAILED_SERVICE_CONTROLLER_CONNECT:
            raise
        print(
            'ERROR: service mode must be started by the Service Control Manager; '
            'run "python -m app" for a console server',
            file=sys.stderr,
            flush=True,
        )
        return 2
    return 0
