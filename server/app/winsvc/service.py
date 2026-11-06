"""The SCM side of ``python -m app service`` (pywin32; Windows only).

PyInstaller needs ``win32timezone`` as a hidden import for this module (Task 13).
"""

from __future__ import annotations

import os
import sys
import threading
import traceback
from typing import Any, ClassVar

import pywintypes
import servicemanager
import win32service
import win32serviceutil

from app.winsvc import DESCRIPTION, DISPLAY_NAME, SERVICE_NAME, STOP_WAIT_HINT_MS
from app.winsvc.host import ServiceHost

_ERROR_FAILED_SERVICE_CONTROLLER_CONNECT = 1063


class McpMonitorService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = DISPLAY_NAME
    _svc_description_ = DESCRIPTION
    host_argv: ClassVar[list[str]] = []

    def __init__(self, args: Any) -> None:
        super().__init__(args)
        self.host = ServiceHost(self.host_argv)
        self._stop_requested = threading.Event()

    def GetAcceptedControls(self) -> int:  # noqa: N802 - pywin32 API
        accepted: int = super().GetAcceptedControls()
        return accepted | win32service.SERVICE_ACCEPT_SHUTDOWN | win32service.SERVICE_ACCEPT_SESSIONCHANGE

    def _request_stop(self) -> None:
        self._stop_requested.set()
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=STOP_WAIT_HINT_MS)
        self.host.stop()

    def SvcStop(self) -> None:  # noqa: N802 - pywin32 API
        self._request_stop()

    def SvcShutdown(self) -> None:  # noqa: N802 - pywin32 API
        self._request_stop()

    def SvcOtherEx(self, control: int, event_type: int, data: Any) -> None:  # noqa: N802 - pywin32 API
        if control == win32service.SERVICE_CONTROL_SESSIONCHANGE:
            self.host.session_change(event_type, data[0])

    def SvcDoRun(self) -> None:  # noqa: N802 - pywin32 API
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)
        try:
            code = self.host.run()
        except BaseException:  # unexpected: still leave through os._exit so the SCM recovers
            servicemanager.LogErrorMsg(traceback.format_exc())
            code = 1
        if not self._stop_requested.is_set() or code != 0:
            # Ended on its own (or failed): exit without reporting STOPPED, so the SCM's recovery
            # actions start the service again (W22).
            servicemanager.LogErrorMsg(f"mcp-monitor exited with code {code}")
            os._exit(code or 1)


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
