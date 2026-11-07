"""Start a session agent (``python -m mcp_agent``) in a given Windows session.

* ``LocalLauncher``: a plain child process; only into the server's own session (a developer PC,
  or the server run inside the RDP session).
* ``WtsLauncher``: the service path. As SYSTEM, take the session user's token
  (``WTSQueryUserToken``) and ``CreateProcessAsUser`` on that session's interactive desktop.
* ``NoLauncher``: launching disabled.

``launch`` blocks for as long as process creation takes (milliseconds); ``AgentProcess.kill`` of
a local agent waits for ``taskkill`` (a fraction of a second).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from app.win import IS_WINDOWS
from app.win.ffi import current_session_id

STILL_ACTIVE = 259
_CREATE_NO_WINDOW = 0x08000000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_DESKTOP = "winsta0\\default"
_SYSTEM_SID = "S-1-5-18"
_TASKKILL_TIMEOUT_SEC = 5


class AgentProcess(Protocol):
    pid: int

    def poll(self) -> int | None:
        """The exit code, or None while it runs."""
        ...

    def kill(self) -> None: ...


@dataclass(frozen=True)
class LaunchSpec:
    session_id: int
    argv: list[str]
    env: dict[str, str]
    """Added to (and overriding) the environment the process would otherwise get."""
    cwd: Path


class LaunchError(Exception):
    """The agent could not be started; the message is a short code or the underlying error's repr."""


class AgentLauncher(Protocol):
    name: str

    def launch(self, spec: LaunchSpec) -> AgentProcess: ...


# --- local ---------------------------------------------------------------------------------


class PopenProcess:
    def __init__(self, popen: subprocess.Popen[bytes]) -> None:
        self._popen = popen
        self.pid = popen.pid

    def poll(self) -> int | None:
        return self._popen.poll()

    def kill(self) -> None:
        """``taskkill /T /F`` (the agent and what it started, e.g. its Edge window); ``Popen.kill``
        if that fails."""
        if self._popen.poll() is not None:
            return
        try:
            done = subprocess.run(
                ["taskkill", "/PID", str(self.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW if IS_WINDOWS else 0,
                timeout=_TASKKILL_TIMEOUT_SEC, check=False,
            )
            if done.returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            self._popen.kill()
        except OSError:  # it ended meanwhile
            pass


class LocalLauncher:
    name = "local"

    def launch(self, spec: LaunchSpec) -> AgentProcess:
        if spec.session_id != current_session_id():
            raise LaunchError("session_mismatch")
        try:
            popen = subprocess.Popen(
                spec.argv,
                env={**os.environ, **spec.env},
                cwd=spec.cwd,
                creationflags=_CREATE_NO_WINDOW if IS_WINDOWS else 0,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except (OSError, ValueError) as exc:
            raise LaunchError(repr(exc)) from exc
        return PopenProcess(popen)


# --- WTS (service) -------------------------------------------------------------------------


class WtsApi(Protocol):
    """The pywin32 calls ``WtsLauncher`` makes (a fake replaces them in tests)."""

    def query_user_token(self, session_id: int, /) -> Any: ...

    def duplicate_token_ex(self, token: Any, /) -> Any:
        """A primary token (``SecurityImpersonation``, ``TOKEN_ALL_ACCESS``)."""
        ...

    def create_environment_block(self, token: Any, /) -> dict[str, str]: ...

    def create_process_as_user(
        self, token: Any, cmdline: str, env: dict[str, str], cwd: str, desktop: str, /
    ) -> tuple[Any, int]:
        """``(process_handle, pid)``; the thread handle is already closed."""
        ...

    def get_exit_code(self, handle: Any, /) -> int: ...

    def terminate(self, handle: Any, /) -> None: ...

    def close_handle(self, handle: Any, /) -> None: ...


class PywinWtsApi:
    """The real ``WtsApi`` (pywin32; imported on first use)."""

    @staticmethod
    def query_user_token(session_id: int) -> Any:
        import win32ts

        return win32ts.WTSQueryUserToken(session_id)

    @staticmethod
    def duplicate_token_ex(token: Any) -> Any:
        import win32con
        import win32security

        return win32security.DuplicateTokenEx(
            token, win32security.SecurityImpersonation, win32con.TOKEN_ALL_ACCESS,
            win32security.TokenPrimary,
        )

    @staticmethod
    def create_environment_block(token: Any) -> dict[str, str]:
        import win32profile

        return dict(win32profile.CreateEnvironmentBlock(token, False))

    @staticmethod
    def create_process_as_user(
        token: Any, cmdline: str, env: dict[str, str], cwd: str, desktop: str
    ) -> tuple[Any, int]:
        import win32process

        si = win32process.STARTUPINFO()
        si.lpDesktop = desktop
        hprocess, hthread, pid, _tid = win32process.CreateProcessAsUser(
            token, None, cmdline, None, None, False,
            _CREATE_UNICODE_ENVIRONMENT | _CREATE_NO_WINDOW, env, cwd, si,
        )
        hthread.Close()
        return hprocess, int(pid)

    @staticmethod
    def get_exit_code(handle: Any) -> int:
        import win32process

        return int(win32process.GetExitCodeProcess(handle))

    @staticmethod
    def terminate(handle: Any) -> None:
        import win32process

        win32process.TerminateProcess(handle, 1)

    @staticmethod
    def close_handle(handle: Any) -> None:
        import win32api

        win32api.CloseHandle(handle)


class HandleProcess:
    """A process started by ``CreateProcessAsUser``; the handle is closed once its exit is seen."""

    def __init__(self, handle: Any, pid: int, api: WtsApi) -> None:
        self._handle = handle
        self.pid = pid
        self._api = api
        self._code: int | None = None

    def poll(self) -> int | None:
        if self._code is not None:
            return self._code
        code = self._api.get_exit_code(self._handle)
        if code == STILL_ACTIVE:
            return None
        self._code = int(code)
        self._api.close_handle(self._handle)
        return self._code

    def kill(self) -> None:
        """``TerminateProcess`` (the agent only; its Edge window closes when it is told ``exit``)."""
        if self._code is not None:
            return
        try:
            self._api.terminate(self._handle)
        except Exception:  # it ended meanwhile, or no access: the next poll tells
            pass


class WtsLauncher:
    name = "wts"

    def __init__(self, api: WtsApi | None = None) -> None:
        self._api: WtsApi = api if api is not None else PywinWtsApi()

    def launch(self, spec: LaunchSpec) -> AgentProcess:
        api = self._api
        handles: list[Any] = []
        try:
            token = api.query_user_token(spec.session_id)
            handles.append(token)
            primary = api.duplicate_token_ex(token)
            handles.append(primary)
            env = {**api.create_environment_block(primary), **spec.env}
            hprocess, pid = api.create_process_as_user(
                primary, subprocess.list2cmdline(spec.argv), env, str(spec.cwd), _DESKTOP
            )
        except Exception as exc:  # pywintypes.error and friends
            raise LaunchError(repr(exc)) from exc
        finally:
            for handle in handles:
                try:
                    api.close_handle(handle)
                except Exception:
                    pass
        return HandleProcess(hprocess, pid, api)


class NoLauncher:
    name = "none"

    def launch(self, spec: LaunchSpec) -> AgentProcess:
        raise LaunchError("disabled")


# --- choice --------------------------------------------------------------------------------


def running_as_system() -> bool:
    """Whether this process runs as LocalSystem (its token user is ``S-1-5-18``)."""
    if not IS_WINDOWS:
        return False
    try:
        import win32api
        import win32con
        import win32security

        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            sid, _attrs = win32security.GetTokenInformation(token, win32security.TokenUser)
        finally:
            token.Close()
        return bool(win32security.ConvertSidToStringSid(sid) == _SYSTEM_SID)
    except Exception:
        return False


def pick_launcher(mode: Literal["auto", "wts", "local", "none"]) -> AgentLauncher:
    """``auto``: ``WtsLauncher`` when running as SYSTEM (the service), else ``LocalLauncher``."""
    if mode == "none":
        return NoLauncher()
    if mode == "wts" or (mode == "auto" and running_as_system()):
        return WtsLauncher()
    return LocalLauncher()
