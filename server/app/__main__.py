import argparse
import asyncio
from pathlib import Path

from app.main import serve


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app", description="MCP monitor server")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="data root (default: cwd)")
    parser.add_argument("--local-port", type=int, default=8700)
    parser.add_argument("--external-port", type=int, default=8701)
    args = parser.parse_args(argv)
    asyncio.run(serve(args.root, args.local_port, args.external_port))


if __name__ == "__main__":
    main()
