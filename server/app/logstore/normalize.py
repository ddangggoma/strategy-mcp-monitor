"""One parsed log event → the indexed columns (ruling W6)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

CATEGORIES: tuple[str, ...] = (
    "session",
    "notice",
    "activity.process",
    "activity.command",
    "activity.window",
    "activity.idle",
    "tamper",
    "mcp.health",
    "mcp.action",
    "auth",
    "admin.audit",
    "system",
)
OUTCOMES = ("ok", "fail", "denied", "error", "failed", "timeout")
SEARCH_MAX_CHARS = 8192

_EVENT_CHARS = 100
_USER_CHARS = 256
_IP_CHARS = 64
_SEARCH_DEPTH = 3
_USER_KEYS = ("user", "actor_email", "email", "actor")


@dataclass(frozen=True)
class Row:
    ts_ms: int
    day: str
    cat: str
    event: str | None
    user: str | None
    session_id: int | None
    client_ip: str | None
    outcome: str | None
    search: str
    raw: str
    line_hash: bytes


def _event(obj: dict[str, Any], cat: str) -> str | None:
    value = obj.get("event")
    if not isinstance(value, str) and cat == "admin.audit":
        value = obj.get("action")
    return value[:_EVENT_CHARS] if isinstance(value, str) else None


def _user(obj: dict[str, Any]) -> str | None:
    for key in _USER_KEYS:
        value = obj.get(key)
        if isinstance(value, str) and value and not (key == "actor" and value == "system"):
            return value[:_USER_CHARS]
    return None


def _client_ip(obj: dict[str, Any]) -> str | None:
    for key in ("client_ip", "ip"):
        value = obj.get(key)
        if isinstance(value, str) and value:
            return value[:_IP_CHARS]
    return None


def _outcome(obj: dict[str, Any], cat: str, event: str | None) -> str | None:
    value: Any = None
    if cat == "auth":
        ok = obj.get("ok")
        if isinstance(ok, bool):
            value = "ok" if ok else "fail"
    elif cat == "admin.audit":
        value = obj.get("result")
    elif cat == "mcp.action":
        value = obj.get("status")
    elif cat == "session" and event == "logon_failed":
        value = "fail"
    return value if isinstance(value, str) and value in OUTCOMES else None


def _is_int64(value: Any) -> bool:
    """An int (not a bool) that fits an SQLite INTEGER."""
    return isinstance(value, int) and not isinstance(value, bool) and -(2**63) <= value < 2**63


def _search_text(obj: dict[str, Any]) -> str:
    """Strings and integers (not bools) among the values, ``ts``/``cat`` left out, to depth 3."""
    parts: list[str] = []
    size = 0

    def walk(value: Any, depth: int) -> None:
        nonlocal size
        if size > SEARCH_MAX_CHARS:
            return
        if isinstance(value, str):
            text = value
        elif isinstance(value, int) and not isinstance(value, bool):
            text = str(value)
        elif depth < _SEARCH_DEPTH and isinstance(value, dict):
            for item in value.values():
                walk(item, depth + 1)
            return
        elif depth < _SEARCH_DEPTH and isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
            return
        else:
            return
        if text:
            parts.append(text)
            size += len(text) + 1

    for key, value in obj.items():
        if key not in ("ts", "cat"):
            walk(value, 1)
    return " ".join(parts)[:SEARCH_MAX_CHARS]


def normalize(obj: dict[str, Any], raw: bytes, day: str) -> Row:
    """The index row of one event that :func:`app.logstore.reader.parse_line` accepted."""
    cat: str = obj["cat"]
    event = _event(obj, cat)
    session_id = obj.get("session_id")
    return Row(
        ts_ms=round(datetime.fromisoformat(obj["ts"]).timestamp() * 1000),
        day=day,
        cat=cat,
        event=event,
        user=_user(obj),
        session_id=session_id if _is_int64(session_id) else None,
        client_ip=_client_ip(obj),
        outcome=_outcome(obj, cat, event),
        search=_search_text(obj),
        raw=raw.decode("utf-8", "replace"),
        line_hash=hashlib.blake2b(raw, digest_size=8).digest(),
    )
