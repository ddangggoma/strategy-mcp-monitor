"""Collector command-line flags (``--session-source``, ``--collect-console``, ``--activity``,
``--agent-launcher``, ``--agent-dialog``, ``--agent-dir``) → ``CollectorConfig``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.activity.agent_supervisor import AgentOptions
from app.clock import Clock
from app.collect.config import CollectorConfig
from app.sessions.jsonsource import JsonFileWtsSource
from app.win.eventlog import EventLogSource, PywinEventLogSource
from app.win.launch import AgentLauncher, pick_launcher
from app.win.wmi import ProcessEventSource, WmiProcessSource
from app.win.wts import CtypesWtsSource, WtsSource

_JSON_PREFIX = "json:"
DEFAULT_AGENT_DIR = Path(__file__).resolve().parents[3] / "agent"


def session_source(value: str) -> str:
    """``wts`` | ``none`` | ``json:<path>`` (argparse ``type``; anything else exits with code 2)."""
    if value in ("wts", "none"):
        return value
    if value.startswith(_JSON_PREFIX) and len(value) > len(_JSON_PREFIX):
        return value
    raise argparse.ArgumentTypeError("expected wts, none or json:<path>")


def add_collector_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--session-source",
        type=session_source,
        default="wts",
        help="RDP session source: wts (default), none, or json:<path> (DEV ONLY: sessions from a file)",
    )
    parser.add_argument(
        "--collect-console",
        action="store_true",
        help="DEV: also track the console session (a PC without RDP sessions)",
    )
    parser.add_argument(
        "--activity",
        choices=("on", "off"),
        default="on",
        help="user activity collection (process events with --session-source wts); "
        "off is for development and E2E runs",
    )
    parser.add_argument(
        "--agent-launcher",
        choices=("auto", "wts", "local", "none"),
        default="auto",
        help="how session agents start: auto (wts as SYSTEM, else local), wts, local "
        "(this session only), none (no agents); ignored with --session-source none",
    )
    parser.add_argument(
        "--agent-dialog",
        choices=("edge", "print"),
        default="edge",
        help="notice window: edge (an Edge app window) or print (DEV/E2E: the agent writes the "
        "notice URL to <root>/run/agent-<session>.url)",
    )
    parser.add_argument(
        "--agent-dir",
        type=Path,
        default=DEFAULT_AGENT_DIR,
        help="the session agent's folder (default: <repo>/agent)",
    )


def collector_config(ns: argparse.Namespace, *, clock: Clock, root: Path) -> CollectorConfig:
    """Build the collector configuration from parsed flags.

    ``wts`` also turns on the event log and, unless ``--activity off``, WMI process events;
    ``none`` and ``json:`` (a PC without real RDP sessions) leave both off. ``root`` is the data
    root (``--agent-dialog print`` writes the notice URL files under ``<root>/run``).
    Without a session source there are no sessions, so no agent launcher either.
    """
    source = ns.session_source
    activity = ns.activity == "on"
    wts: WtsSource | None
    event_log: EventLogSource | None = None
    process: ProcessEventSource | None = None
    if source == "wts":
        wts = CtypesWtsSource(clock)
        event_log = PywinEventLogSource()
        if activity:
            process = WmiProcessSource()
    elif source == "none":
        wts = None
    else:
        path = Path(source.removeprefix(_JSON_PREFIX))
        print(f"WARNING: dev session source {path}", file=sys.stderr, flush=True)
        wts = JsonFileWtsSource(path, clock)
    launcher: AgentLauncher | None = None
    if wts is not None and ns.agent_launcher != "none":
        launcher = pick_launcher(ns.agent_launcher)
    agent = AgentOptions(
        dialog=ns.agent_dialog,
        agent_dir=ns.agent_dir,
        url_dir=root / "run" if ns.agent_dialog == "print" else None,
    )
    return CollectorConfig(
        wts=wts, collect_console=ns.collect_console, event_log=event_log,
        process=process, activity=activity, launcher=launcher, agent=agent,
    )
