import argparse
import asyncio
import ipaddress
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from app.clock import SystemClock
from app.collect.cli import add_collector_arguments, collector_config
from app.logstore.indexer import IndexStatus, LogIndex
from app.main import serve
from app.paths import AppPaths

DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[2] / "web" / "dist"


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
    parser = argparse.ArgumentParser(prog="python -m app", description="MCP monitor server")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="data root (default: cwd)")
    parser.add_argument("--local-port", type=int, default=8700)
    parser.add_argument("--external-port", type=int, default=8701)
    parser.add_argument(
        "--external-host", default="0.0.0.0", help="address of the external channel (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--static-dir", type=Path, default=DEFAULT_STATIC_DIR, help="built web app (default: web/dist)"
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
    add_collector_arguments(parser)
    args = parser.parse_args(argv)
    if args.dev_otp_code is not None and not args.allow_lan_dev and not _is_loopback(args.external_host):
        parser.error(
            f"--dev-otp-code with --external-host {args.external_host} would let anyone on the network "
            "log in with a fixed code; bind --external-host 127.0.0.1 or pass --allow-lan-dev"
        )
    return args


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
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="data root (default: cwd)")
    ns = parser.parse_args(argv)
    paths = AppPaths(ns.root)
    paths.ensure()
    db = paths.index_db_path
    for p in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
        p.unlink(missing_ok=True)
    status = asyncio.run(_reindex(paths))
    print(f"indexed {status.rows} rows from {status.files} files", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if args[:1] == ["reindex"]:
        return reindex(args[1:])
    ns = parse_args(args)
    asyncio.run(
        serve(
            ns.root,
            ns.local_port,
            ns.external_port,
            external_host=ns.external_host,
            static_dir=ns.static_dir,
            dev_otp_code=ns.dev_otp_code,
            collectors=collector_config(ns, clock=SystemClock(), root=ns.root),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
