"""Command line and environment of the session agent."""

from __future__ import annotations

import argparse
import os
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TOKEN_ENV = "MCPMON_AGENT_TOKEN"


@dataclass(frozen=True)
class AgentConfig:
    server: str
    token: str
    dialog: Literal["edge", "print"]
    url_file: Path | None
    edge_path: str | None
    profile_dir: Path
    unreachable_exit_sec: float


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mcp_agent", description="MCP Monitor session agent")
    p.add_argument("--server", required=True, help="Local channel base URL, e.g. http://127.0.0.1:8700")
    p.add_argument("--dialog", choices=("edge", "print"), default="edge")
    p.add_argument("--url-file", type=Path, help="print dialog: append OPEN/CLOSE lines here")
    p.add_argument("--edge-path")
    p.add_argument("--profile-dir", type=Path)
    p.add_argument("--unreachable-exit-sec", type=float, default=120.0)
    return p


def parse_args(argv: list[str], environ: MutableMapping[str, str]) -> AgentConfig:
    # Take the token out first, whatever happens next, so children (Edge) never inherit it (V17).
    token = environ.pop(TOKEN_ENV, None)
    parser = _parser()
    args = parser.parse_args(argv)
    if not token:
        parser.error(f"{TOKEN_ENV} is not set")
    if args.dialog == "print" and args.url_file is None:
        parser.error("--dialog print needs --url-file")
    local = environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return AgentConfig(
        server=args.server.rstrip("/"),
        token=token,
        dialog=args.dialog,
        url_file=args.url_file,
        edge_path=args.edge_path,
        profile_dir=args.profile_dir or Path(local) / "mcp-monitor" / "notice-edge",
        unreachable_exit_sec=args.unreachable_exit_sec,
    )
