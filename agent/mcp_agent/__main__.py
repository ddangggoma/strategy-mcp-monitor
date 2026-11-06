"""``python -m mcp_agent --server http://127.0.0.1:8700 [--dialog edge|print] ...``

The per-launch token comes in ``MCPMON_AGENT_TOKEN`` and is removed from the environment at once.
"""

from __future__ import annotations

import os
import sys

from mcp_agent import win32
from mcp_agent.client import ServerClient
from mcp_agent.config import parse_args
from mcp_agent.dialog import EdgeWindow, NoticeWindow, PrintWindow, find_edge
from mcp_agent.runner import AgentRunner


def main(argv: list[str] | None = None) -> int:
    cfg = parse_args(sys.argv[1:] if argv is None else argv, os.environ)
    client = ServerClient(cfg.server, cfg.token)
    window: NoticeWindow
    if cfg.dialog == "print":
        assert cfg.url_file is not None  # parse_args requires it
        window = PrintWindow(cfg.url_file)
    else:
        window = EdgeWindow(cfg.edge_path or find_edge(), cfg.profile_dir)
    return AgentRunner(cfg, client, window, session_id=win32.current_session_id(), pid=os.getpid()).run()


if __name__ == "__main__":
    sys.exit(main())
