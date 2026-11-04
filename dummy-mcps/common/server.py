"""Shared launcher for the dummy MCP servers (FastMCP-style server over streamable HTTP + optional chaos)."""
from __future__ import annotations

import argparse
import functools
import os
import signal
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from common.chaos import ChaosState, SlowMiddleware, chaos_routes

ToolsArg = Sequence[Callable] | Callable[[argparse.Namespace], Sequence[Callable]]


def _report_value_errors(fn: Callable) -> Callable:
    """Surface a tool's ValueError (bad input) as a tool error carrying its message, not as a server crash."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as e:
            raise ToolError(str(e)) from None
    return wrapper


def _exit_cleanly(signum: int, frame: object) -> None:
    sys.exit(0)


def build_parser(name: str, default_port: int) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=name, description=f"Dummy MCP server: {name}")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=default_port)
    p.add_argument("--chaos", action="store_true", help="register /chaos/{crash,hang,slow}")
    p.add_argument("--pid-file", type=Path, default=None, help="write os.getpid() here; removed on clean exit")
    return p


def run(name: str, tools: ToolsArg, argv: Sequence[str] | None, default_port: int, *,
        extra_args: Callable[[argparse.ArgumentParser], None] | None = None) -> None:
    """Serve `tools` at http://host:port/mcp.

    `extra_args` adds per-server CLI flags (e.g. --open-meteo); `tools` may be a factory taking the
    parsed Namespace so flags can shape the tool wrappers.
    """
    parser = build_parser(name, default_port)
    if extra_args is not None:
        extra_args(parser)
    args = parser.parse_args(argv)
    tool_list = tools(args) if callable(tools) else tools

    mcp = MCPServer(name)
    for fn in tool_list:
        mcp.tool()(_report_value_errors(fn))
    app = mcp.streamable_http_app(host=args.host)

    state = ChaosState()
    if args.chaos:
        app.router.routes.extend(chaos_routes(state))

    server = uvicorn.Server(uvicorn.Config(SlowMiddleware(app, state), host=args.host, port=args.port,
                                           log_level="warning"))
    if args.pid_file:
        args.pid_file.write_text(str(os.getpid()))
    # uvicorn restores the previous handler and re-raises a captured signal after shutting down. The Windows
    # default for Ctrl+Break/SIGTERM kills the process on the spot (skipping `finally`), so give it a handler
    # that unwinds normally instead.
    for sig in (getattr(signal, "SIGBREAK", None), signal.SIGTERM):
        if sig is not None:
            signal.signal(sig, _exit_cleanly)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        if args.pid_file:
            args.pid_file.unlink(missing_ok=True)
