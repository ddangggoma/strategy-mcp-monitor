from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

KST = timezone(timedelta(hours=9), "KST")
_OFFSET = re.compile(r"^([+-])(\d{2}):(\d{2})$")


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _parse_tz(tz: str) -> tzinfo:
    m = _OFFSET.match(tz)
    if m:
        hours, minutes = int(m.group(2)), int(m.group(3))
        if hours > 23 or minutes > 59:
            raise ValueError(f"invalid UTC offset: {tz!r}")
        delta = timedelta(hours=hours, minutes=minutes)
        return timezone(-delta if m.group(1) == "-" else delta)
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError(f"unknown timezone: {tz!r}") from None


def convert_timezone(time: str, tz: str) -> str:
    """Convert an ISO-8601 time (naive input is taken as KST) to an IANA zone or a +HH:MM offset."""
    target = _parse_tz(tz)
    try:
        moment = datetime.fromisoformat(time)
    except (ValueError, TypeError):
        raise ValueError(f"invalid ISO-8601 time: {time!r}") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=KST)
    return moment.astimezone(target).isoformat()
