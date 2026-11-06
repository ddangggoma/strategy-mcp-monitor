"""The daily log files in the logs folder: ``YYYY-MM-DD.jsonl`` (live) and ``YYYY-MM-DD.jsonl.gz``."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

LOG_NAME = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})\.jsonl(\.gz)?", re.ASCII)


@dataclass(frozen=True)
class LogFile:
    name: str
    day: date
    compressed: bool
    path: Path
    size: int


def list_log_files(logs_dir: Path) -> list[LogFile]:
    """Every ``YYYY-MM-DD.jsonl[.gz]`` regular file with a real calendar date, by ``(day, compressed)``."""
    found: list[LogFile] = []
    try:
        entries = list(Path(logs_dir).iterdir())
    except OSError:  # no logs directory yet (or unreadable): nothing to list
        return found
    for entry in entries:
        m = LOG_NAME.fullmatch(entry.name)
        if m is None:
            continue
        try:
            day = date.fromisoformat(m.group(1))
            if not entry.is_file():
                continue
            size = entry.stat().st_size
        except (ValueError, OSError):  # 2026-13-01, or the file vanished meanwhile
            continue
        found.append(LogFile(entry.name, day, m.group(2) is not None, entry, size))
    found.sort(key=lambda f: (f.day, f.compressed))
    return found
