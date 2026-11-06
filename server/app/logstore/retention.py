"""Read-only preview of what a log retention setting would delete (nothing is deleted here)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from app.logstore.files import list_log_files


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


def preview(logs_dir: Path, today: date, days: int) -> RetentionPreview:
    cutoff = retention_cutoff(today, days)
    files = [(f.day, f.size) for f in list_log_files(Path(logs_dir))]
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
