"""``python -m tests.desktop_bundle_main <mcp-monitor.exe> <server arguments…>``: ``python -m app`` as
if it ran from a desktop bundle whose root holds ``<mcp-monitor.exe>`` (``app.bundle``), so the
session agent it starts is the Rust ``mcp-monitor.exe agent``. Development has no bundle; the agent
integration tests use this to run the service-stop scenario with the desktop agent (Plan 6 Task 11).
"""

import sys
from pathlib import Path

import app.__main__ as server_main
from app import __version__
from app.bundle import DESKTOP_EXE, Bundle


def main(argv: list[str]) -> int:
    exe = Path(argv[0])
    if exe.name.lower() != DESKTOP_EXE:
        print(f"ERROR: expected a path to {DESKTOP_EXE}, got {exe}", file=sys.stderr, flush=True)
        return 2
    bundle = Bundle(exe.parent, "pyinstaller", __version__, "desktop")
    server_main.find_bundle = lambda executable=None: bundle  # type: ignore[assignment]
    return server_main.main(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
