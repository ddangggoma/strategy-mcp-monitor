"""Where the deployment bundle is, and the defaults that follow from it (Plan 5 Task 9).

A bundle (built by ``build.ps1``, Task 13) has a ``bundle.json`` at its root, e.g.
``{"layout": "runtime", "version": "1.0.0", "python": "3.15.2", ...}``:

* ``pyinstaller``: ``bin\\monitor\\mcp-monitor.exe`` and ``bin\\agent\\mcp-agent.exe``;
* ``runtime``: an embeddable Python in ``runtime\\`` whose ``._pth`` adds ``..\\server`` and
  ``..\\agent`` (the agent runs as ``runtime\\python.exe -m mcp_agent``).

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

BUNDLE_FILE = "bundle.json"
_SEARCH_LEVELS = 3
_REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Bundle:
    root: Path
    layout: Layout
    version: str


def find_bundle(executable: Path | None = None) -> Bundle | None:
    """The bundle ``executable`` (default: this interpreter or frozen exe) belongs to: the nearest
    ``bundle.json`` in its folder or up to two folders above. A ``bundle.json`` that is unreadable
    or not ``{"layout": "pyinstaller" | "runtime", "version": "<non-empty>", ...}`` means no bundle
    (the search does not go on past it)."""
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
        return Bundle(folder, cast(Layout, layout), version)
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
    if b.layout == "pyinstaller":
        return (str(b.root / "bin" / "agent" / "mcp-agent.exe"),)
    return (str(b.root / "runtime" / "python.exe"), "-m", "mcp_agent")
