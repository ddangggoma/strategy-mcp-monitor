"""The ``mcp-monitor`` service's start type: read it from the SCM and apply the setting.

``StartTypeManager.reconcile()`` runs when the service starts and when an admin saves a new
``service_start_type``; both call it off the event loop (it blocks on the SCM).
"""

from __future__ import annotations

import sys
from typing import Any, Literal, Protocol

from app.bundle import find_bundle
from app.settings.store import SettingsStore
from app.winsvc import SERVICE_NAME

StartType = Literal["auto", "delayed-auto", "manual"]
# What the SCM can report: an admin may have disabled the service (incident response); that is never
# a setting and never overwritten by one (plan review minor 17).
CurrentStartType = Literal["auto", "delayed-auto", "manual", "disabled"]
ReconcileResult = Literal["applied", "in_sync", "not_installed", "disabled", "denied", "error"]

_ERROR_ACCESS_DENIED = 5
_ERROR_SERVICE_DOES_NOT_EXIST = 1060
_SERVICE_AUTO_START = 2
_SERVICE_DEMAND_START = 3
_SERVICE_DISABLED = 4


class ServiceConfigurator(Protocol):
    def query(self) -> CurrentStartType | None:
        """The installed service's start type; ``None`` when the service is not installed."""
        ...

    def apply(self, st: StartType) -> None:
        """Set the start type. ``PermissionError`` without the right, ``OSError`` otherwise."""
        ...


class LogSinkThreadsafe(Protocol):
    def emit_threadsafe(self, cat: str, **fields: Any) -> None: ...


def _os_error(exc: Any) -> OSError:
    """``pywintypes.error`` → ``PermissionError`` (access denied) or ``OSError``."""
    winerror = getattr(exc, "winerror", None)
    message = f"{getattr(exc, 'funcname', '')}: {getattr(exc, 'strerror', exc)}"
    if winerror == _ERROR_ACCESS_DENIED:
        return PermissionError(winerror, message)
    return OSError(winerror, message)


class ScmConfigurator:
    """The real SCM (pywin32). Querying needs no admin; applying does."""

    def __init__(self, name: str = SERVICE_NAME) -> None:
        self.name = name

    def _with_service(self, access: int, fn: Any) -> Any:
        import pywintypes
        import win32service

        try:
            scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
            try:
                handle = win32service.OpenService(scm, self.name, access)
                try:
                    return fn(win32service, handle)
                finally:
                    win32service.CloseServiceHandle(handle)
            finally:
                win32service.CloseServiceHandle(scm)
        except pywintypes.error as exc:
            if exc.winerror == _ERROR_SERVICE_DOES_NOT_EXIST:
                raise LookupError(self.name) from None
            raise _os_error(exc) from None

    def query(self) -> CurrentStartType | None:
        import win32service

        def read(svc: Any, handle: Any) -> CurrentStartType:
            start = svc.QueryServiceConfig(handle)[1]
            if start == _SERVICE_DISABLED:
                return "disabled"
            if start != _SERVICE_AUTO_START:
                return "manual"  # demand start; the driver start types read as manual
            delayed = svc.QueryServiceConfig2(handle, svc.SERVICE_CONFIG_DELAYED_AUTO_START_INFO)
            return "delayed-auto" if delayed else "auto"

        try:
            return self._with_service(win32service.SERVICE_QUERY_CONFIG, read)
        except LookupError:
            return None

    def apply(self, st: StartType) -> None:
        import win32service

        def change(svc: Any, handle: Any) -> None:
            start = _SERVICE_DEMAND_START if st == "manual" else _SERVICE_AUTO_START
            svc.ChangeServiceConfig(
                handle, svc.SERVICE_NO_CHANGE, start, svc.SERVICE_NO_CHANGE,
                None, None, 0, None, None, None, None,
            )
            svc.ChangeServiceConfig2(handle, svc.SERVICE_CONFIG_DELAYED_AUTO_START_INFO, st == "delayed-auto")

        access = win32service.SERVICE_QUERY_CONFIG | win32service.SERVICE_CHANGE_CONFIG
        try:
            self._with_service(access, change)
        except LookupError:
            raise OSError(_ERROR_SERVICE_DOES_NOT_EXIST, f"service {self.name} is not installed") from None

    def set_preshutdown_timeout(self, ms: int) -> None:
        """How long the SCM waits for the service at OS shutdown once it accepts PRESHUTDOWN (plan
        review I5); the service sets it on itself when it starts. ``LookupError`` when not installed."""
        import win32service

        def change(svc: Any, handle: Any) -> None:
            svc.ChangeServiceConfig2(handle, svc.SERVICE_CONFIG_PRESHUTDOWN_INFO, ms)

        self._with_service(win32service.SERVICE_CHANGE_CONFIG, change)

    def preshutdown_timeout(self) -> int | None:
        """The service's preshutdown timeout in ms (no admin needed); ``None`` when not installed."""
        import win32service

        def read(svc: Any, handle: Any) -> int:
            return int(svc.QueryServiceConfig2(handle, svc.SERVICE_CONFIG_PRESHUTDOWN_INFO))

        try:
            return int(self._with_service(win32service.SERVICE_QUERY_CONFIG, read))
        except LookupError:
            return None


class NullConfigurator:
    """No SCM (not Windows): never installed."""

    def query(self) -> CurrentStartType | None:
        return None

    def apply(self, st: StartType) -> None:
        raise LookupError("no service control manager on this platform")


def default_configurator() -> ServiceConfigurator:
    return ScmConfigurator() if sys.platform == "win32" else NullConfigurator()


class StartTypeManager:
    """Compares the setting with the SCM. ``configurator`` is public (tests replace it)."""

    def __init__(self, configurator: ServiceConfigurator, settings: SettingsStore, log: LogSinkThreadsafe) -> None:
        self.configurator = configurator
        self._settings = settings
        self._log = log
        self.running_as_service = False
        # F20: only a deployment bundle can be installed as the service; a development run cannot
        self.bundled = find_bundle() is not None

    def status(self, desired: StartType | None = None) -> dict[str, Any]:
        """Blocking (SCM query). A query error reads as "not installed". Callers off the loop
        pass ``desired`` (read on the loop thread: config.db rule); otherwise it is read here."""
        if desired is None:
            desired = self._settings.get().service_start_type
        try:
            current = self.configurator.query()
        except OSError:
            current = None
        return {
            "installed": current is not None,
            "running_as_service": self.running_as_service,
            "start_type": current,
            "desired": desired,
            "in_sync": current is not None and current == desired,
            "bundle": self.bundled,
        }

    def reconcile(self, desired: StartType | None = None) -> ReconcileResult:
        """Blocking: apply the desired start type when it differs; logs ``service.start_type``
        (``emit_threadsafe``: it runs off the loop). ``desired`` as in :meth:`status`."""
        if desired is None:
            desired = self._settings.get().service_start_type
        current: CurrentStartType | None = None
        result: ReconcileResult
        try:
            current = self.configurator.query()
            if current is None:
                result = "not_installed"
            elif current == "disabled":
                result = "disabled"  # an admin's decision in the SCM: never re-enabled from here
            elif current == desired:
                result = "in_sync"
            else:
                self.configurator.apply(desired)
                result = "applied"
        except PermissionError:
            result = "denied"
        except (OSError, LookupError):
            result = "error"
        self._log.emit_threadsafe(
            "system", event="service.start_type", result=result, desired=desired, current=current
        )
        return result
