import argparse
import asyncio
import ipaddress
import re
from pathlib import Path

from app.main import serve

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
    args = parser.parse_args(argv)
    if args.dev_otp_code is not None and not args.allow_lan_dev and not _is_loopback(args.external_host):
        parser.error(
            f"--dev-otp-code with --external-host {args.external_host} would let anyone on the network "
            "log in with a fixed code; bind --external-host 127.0.0.1 or pass --allow-lan-dev"
        )
    return args


def main(argv: list[str] | None = None) -> None:
    ns = parse_args(argv)
    asyncio.run(
        serve(
            ns.root,
            ns.local_port,
            ns.external_port,
            external_host=ns.external_host,
            static_dir=ns.static_dir,
            dev_otp_code=ns.dev_otp_code,
        )
    )


if __name__ == "__main__":
    main()
