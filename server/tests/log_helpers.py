"""Log-file and index helpers shared by the log index, query, API and retention tests."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any


def ev(ts: str, cat: str, **fields: Any) -> bytes:
    """One JSONL log line (without the newline)."""
    return json.dumps({"ts": ts, "cat": cat, **fields}, ensure_ascii=False).encode()


def write_lines(logs_dir: Path, day: str, lines: list[bytes]) -> Path:
    """Append ``lines`` (each followed by ``\\n``) to ``<logs_dir>/<day>.jsonl``; creates the folder."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"{day}.jsonl"
    with path.open("ab") as fh:
        fh.write(b"".join(line + b"\n" for line in lines))
    return path


def write_gz(logs_dir: Path, day: str, lines: list[bytes]) -> Path:
    """Write ``<logs_dir>/<day>.jsonl.gz`` holding ``lines`` (each followed by ``\\n``)."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"{day}.jsonl.gz"
    with gzip.open(path, "wb") as fh:
        fh.write(b"".join(line + b"\n" for line in lines))
    return path


async def index_all(services: Any) -> None:
    """Write what the log writer holds, then index until the index is ready (at most 1,000 cycles)."""
    await services.log.flush()
    for _ in range(1000):
        await services.log_index.index_once()
        if services.log_index.status().ready:
            return
    raise AssertionError("the log index did not become ready within 1,000 cycles")
