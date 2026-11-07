import argparse
import asyncio
import ipaddress
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from app import __version__
from app.bundle import default_root, default_static_dir, find_bundle
from app.clock import SystemClock
from app.collect.cli import add_collector_arguments, collector_config
from app.db import DatabaseTooNewError
from app.logstore.indexer import IndexStatus, LogIndex
from app.main import PortInUseError, ServeControl, serve
from app.paths import AppPaths
from app.rootlock import RootInUseError, RootLock

_ROOT_HELP = r"data root (default: %%ProgramData%%\MCP Monitor in a deployment bundle, else cwd)"


def _dev_otp_code(value: str) -> str:
    # fullmatch, not "^...$": `$` would also accept a trailing newline.
    if re.fullmatch(r"[0-9]{6}", value) is None:
        raise argparse.ArgumentTypeError("must be exactly 6 ASCII digits")
    return value


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    bundle = find_bundle()
    parser = argparse.ArgumentParser(prog="python -m app", description="MCP monitor server")
    parser.add_argument("--version", action="version", version=f"mcp-monitor {__version__}")
    parser.add_argument(
        "--root", type=Path, default=default_root(bundle),
        help=_ROOT_HELP,
    )
    parser.add_argument("--local-port", type=int, default=8700)
    parser.add_argument("--external-port", type=int, default=8701)
    parser.add_argument(
        "--external-host", default="0.0.0.0", help="address of the external channel (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--static-dir", type=Path, default=default_static_dir(bundle),
        help="built web app (default: <bundle>/web, else web/dist)",
    )
    parser.add_argument(
        "--dev-otp-code",
        type=_dev_otp_code,
        default=None,
        help="DEV ONLY: accept this fixed 6-digit code as every user's login code",
    )
    parser.add_argument(
        "--allow-lan-dev",
        action="store_true",
        help="allow --dev-otp-code while the external channel is reachable from the network",
    )
    add_collector_arguments(parser, bundle)
    args = parser.parse_args(argv)
    if args.dev_otp_code is not None and not args.allow_lan_dev and not _is_loopback(args.external_host):
        parser.error(
            f"--dev-otp-code with --external-host {args.external_host} would let anyone on the network "
            "log in with a fixed code; bind --external-host 127.0.0.1 or pass --allow-lan-dev"
        )
    return args


# Exit codes (W23): 0 ok, 1 unexpected error, 2 arguments (argparse), and these three.
EXIT_PORT_IN_USE = 3
EXIT_ROOT_IN_USE = 4
EXIT_DATABASE_TOO_NEW = 5


def _error(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr, flush=True)


class _StderrLog:
    """The reindex command's log sink: ``logindex.*`` lines go to stderr (no LogWriter)."""

    def emit(self, cat: str, *, at: datetime | None = None, **fields: Any) -> None:  # noqa: ARG002
        print(json.dumps({"cat": cat, **fields}, ensure_ascii=False, default=str), file=sys.stderr, flush=True)


async def _reindex(paths: AppPaths) -> IndexStatus:
    index = LogIndex(paths.index_db_path, paths.logs_dir, SystemClock(), _StderrLog())
    await index.start(run_loop=False)
    try:
        while True:
            await index.index_once()
            if index.status().ready:
                return index.status()
    finally:
        await index.stop()


def reindex(argv: list[str]) -> int:
    """``python -m app reindex [--root PATH]``: delete ``index.db`` and index the JSONL files again."""
    parser = argparse.ArgumentParser(
        prog="python -m app reindex", description="rebuild the log search index from the JSONL files"
    )
    parser.add_argument(
        "--root", type=Path, default=default_root(find_bundle()),
        help=_ROOT_HELP,
    )
    ns = parser.parse_args(argv)
    root = ns.root.resolve()
    paths = AppPaths(root)
    paths.ensure()
    lock = RootLock(root)
    try:
        lock.acquire()  # never rebuild the index under a running server (exit 4)
    except RootInUseError:
        _error(f"data root {root} is already in use by another MCP Monitor process")
        return EXIT_ROOT_IN_USE
    try:
        db = paths.index_db_path
        for p in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
            p.unlink(missing_ok=True)
        status = asyncio.run(_reindex(paths))
    finally:
        lock.release()
    print(f"indexed {status.rows} rows from {status.files} files", flush=True)
    return 0


def run_server(ns: argparse.Namespace, control: ServeControl | None = None) -> int:
    """Run the server until it stops; the expected startup failures become exit codes 3/4/5
    with one line on stderr and no traceback (W23)."""
    root = ns.root.resolve()
    try:
        asyncio.run(
            serve(
                root,
                ns.local_port,
                ns.external_port,
                external_host=ns.external_host,
                static_dir=ns.static_dir,
                dev_otp_code=ns.dev_otp_code,
                collectors=collector_config(ns, clock=SystemClock(), root=root),
                control=control,
            )
        )
    except PortInUseError as exc:
        _error(f"port {exc.port} is already in use ({exc.host})")
        return EXIT_PORT_IN_USE
    except RootInUseError:
        _error(f"data root {root} is already in use by another MCP Monitor process")
        return EXIT_ROOT_IN_USE
    except DatabaseTooNewError as exc:
        _error(
            f"{AppPaths(root).db_path} was written by a newer version (schema {exc.found} > "
            f"{exc.supported}); install that version or restore a backup"
        )
        return EXIT_DATABASE_TOO_NEW
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if args[:1] == ["service"]:
        from app.winsvc.service import dispatch  # pywin32: Windows only

        return dispatch(args[1:])
    if args[:1] == ["reindex"]:
        return reindex(args[1:])
    return run_server(parse_args(args))


if __name__ == "__main__":
    sys.exit(main())
