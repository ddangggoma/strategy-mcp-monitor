"""Where the deployment bundle is, and the defaults that follow from it (Plan 5 Task 9, Plan 6 Task 2).

A bundle (the payload ``install/build.ps1`` builds) has a ``bundle.json`` at its root, e.g.
``{"layout": "pyinstaller", "version": "1.0.0", "python": "3.15.2", ..., "agent": "desktop"}``:

* ``pyinstaller``: the server is ``bin\\monitor\\mcp-monitor-server.exe`` (Plan 6; ``mcp-monitor.exe``
  in the earlier PowerShell install);
* ``runtime``: an embeddable Python in ``runtime\\`` whose ``._pth`` adds ``..\\server`` and
  ``..\\agent`` (the agent runs as ``runtime\\python.exe -m mcp_agent``).

``agent`` says which session agent the bundle carries:

* ``desktop`` (Plan 6, the shipped form): the Rust ``mcp-monitor.exe`` at the bundle root, run as
  ``mcp-monitor.exe agent``; its notice window is a WebView2 window (``--dialog webview``);
* ``python`` (the default when the key is missing, a bundle of the earlier PowerShell install):
  ``bin\\agent\\mcp-agent.exe`` or ``runtime\\python.exe -m mcp_agent``, whose notice window is an Edge app window.

The bundle sits under Program Files, so the agent's executable is readable by every user session
(the ``WtsLauncher`` starts it as the session user). Without a bundle (development) the defaults
stay what they were: data root = cwd, the web app from ``<repo>/web/dist``, and the agent runs on
the base interpreter with ``PYTHONPATH`` = ``<repo>/agent``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

Layout = Literal["pyinstaller", "runtime"]
AgentKind = Literal["python", "desktop"]

BUNDLE_FILE = "bundle.json"
DESKTOP_EXE = "mcp-monitor.exe"
_SEARCH_LEVELS = 3
_REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Bundle:
    root: Path
    layout: Layout
    version: str
    agent: AgentKind = "python"


def find_bundle(executable: Path | None = None) -> Bundle | None:
    """The bundle ``executable`` (default: this interpreter or frozen exe) belongs to: the nearest
    ``bundle.json`` in its folder or up to two folders above. A ``bundle.json`` that is unreadable
    or not ``{"layout": "pyinstaller" | "runtime", "version": "<non-empty>", ...}`` with an optional
    ``"agent": "python" | "desktop"`` means no bundle (the search does not go on past it)."""
    exe = Path(sys.executable) if executable is None else executable
    for folder in list(exe.parents)[:_SEARCH_LEVELS]:
        candidate = folder / BUNDLE_FILE
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        layout, version = data.get("layout"), data.get("version")
        if layout not in ("pyinstaller", "runtime") or not isinstance(version, str) or not version:
            return None
        agent = data.get("agent", "python")
        if agent not in ("python", "desktop"):
            return None
        return Bundle(folder, cast(Layout, layout), version, cast(AgentKind, agent))
    return None


def default_static_dir(b: Bundle | None) -> Path:
    """The built web app: ``<bundle>/web``, else ``<repo>/web/dist``."""
    return b.root / "web" if b is not None else _REPO / "web" / "dist"


def default_root(b: Bundle | None) -> Path:
    """The data root: ``%ProgramData%\\MCP Monitor`` for a bundle, else the current folder."""
    if b is None:
        return Path.cwd()
    return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "MCP Monitor"


def agent_command(b: Bundle | None, python: str = sys.executable) -> tuple[str, ...]:
    """How the session agent starts (the supervisor appends ``--server …``)."""
    if b is None:
        return (python, "-m", "mcp_agent")
    if b.agent == "desktop":
        return (str(b.root / DESKTOP_EXE), "agent")
    if b.layout == "pyinstaller":
        return (str(b.root / "bin" / "agent" / "mcp-agent.exe"),)
    return (str(b.root / "runtime" / "python.exe"), "-m", "mcp_agent")


def default_agent_dialog(b: Bundle | None) -> Literal["edge", "webview"]:
    """The notice window the bundle's agent shows: ``webview`` (the desktop agent's WebView2
    window) in a desktop bundle, else ``edge`` (the Python agent's Edge app window)."""
    return "webview" if b is not None and b.agent == "desktop" else "edge"
