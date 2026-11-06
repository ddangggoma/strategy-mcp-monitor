"""Collector command-line flags (``--session-source``, ``--collect-console``) → ``CollectorConfig``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.clock import Clock
from app.collect.config import CollectorConfig
from app.sessions.jsonsource import JsonFileWtsSource
from app.win.wts import CtypesWtsSource, WtsSource

_JSON_PREFIX = "json:"


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


def collector_config(ns: argparse.Namespace, *, clock: Clock, root: Path) -> CollectorConfig:
    """Build the collector configuration from parsed flags.

    ``root`` is the data root; nothing uses it yet (Task 7 keeps the event-log bookmarks under it).
    """
    source = ns.session_source
    wts: WtsSource | None
    if source == "wts":
        wts = CtypesWtsSource(clock)
    elif source == "none":
        wts = None
    else:
        path = Path(source.removeprefix(_JSON_PREFIX))
        print(f"WARNING: dev session source {path}", file=sys.stderr, flush=True)
        wts = JsonFileWtsSource(path, clock)
    return CollectorConfig(wts=wts, collect_console=ns.collect_console)
