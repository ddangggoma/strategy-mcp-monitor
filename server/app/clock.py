from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

KST = timezone(timedelta(hours=9))


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current time as a UTC-aware datetime."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def to_kst_iso(dt: datetime) -> str:
    """Format as ISO 8601 with millisecond precision and +09:00 offset."""
    return dt.astimezone(KST).isoformat(timespec="milliseconds")
