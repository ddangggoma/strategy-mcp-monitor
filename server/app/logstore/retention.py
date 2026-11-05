"""Read-only preview of what a log retention setting would delete (nothing is deleted here)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

_LOG_NAME = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})\.jsonl(\.gz)?", re.ASCII)


def retention_cutoff(today: date, days: int) -> date:
    """The oldest date kept: ``days`` dates including ``today``. Files dated before it are deletable."""
    return today - timedelta(days=days - 1)


@dataclass(frozen=True)
class RetentionPreview:
    days: int
    cutoff: date
    total_files: int
    total_bytes: int
    oldest_date: date | None
    delete_files: int
    delete_bytes: int
    delete_from: date | None
    delete_to: date | None


def _log_files(logs_dir: Path) -> list[tuple[date, int]]:
    """``(date, size)`` of every ``YYYY-MM-DD.jsonl[.gz]`` regular file with a real calendar date."""
    found: list[tuple[date, int]] = []
    try:
        entries = list(logs_dir.iterdir())
    except OSError:  # no logs directory yet (or unreadable): nothing to count
        return found
    for entry in entries:
        m = _LOG_NAME.fullmatch(entry.name)
        if m is None:
            continue
        try:
            day = date.fromisoformat(m.group(1))
            if not entry.is_file():
                continue
            found.append((day, entry.stat().st_size))
        except (ValueError, OSError):  # 2026-13-01, or the file vanished meanwhile
            continue
    return found


def preview(logs_dir: Path, today: date, days: int) -> RetentionPreview:
    cutoff = retention_cutoff(today, days)
    files = _log_files(Path(logs_dir))
    doomed = [(d, size) for d, size in files if d < cutoff]
    return RetentionPreview(
        days=days,
        cutoff=cutoff,
        total_files=len(files),
        total_bytes=sum(size for _, size in files),
        oldest_date=min((d for d, _ in files), default=None),
        delete_files=len(doomed),
        delete_bytes=sum(size for _, size in doomed),
        delete_from=min((d for d, _ in doomed), default=None),
        delete_to=max((d for d, _ in doomed), default=None),
    )
