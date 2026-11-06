"""A ``WtsSource`` that reads sessions from a JSON file — development and E2E only (V24).

The file is ``{"sessions": [{...}]}`` and is re-read on every snapshot, so a test can add, change and
remove sessions while the server runs. ``"session_id": "self"`` stands for this process's own
Windows session (so the real agent launcher and peer checks work on a PC without RDP).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from app.clock import Clock
from app.win.ffi import current_session_id
from app.win.wts import STATE_NAMES, WtsError, WtsProtocol, WtsSession, WtsSnapshot

_PROTOCOLS: tuple[WtsProtocol, ...] = ("console", "rdp", "other")


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _opt_str(item: dict[str, Any], key: str) -> str | None:
    v = item.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise WtsError(f"{key}: expected a string")
    return v or None


def _opt_dt(item: dict[str, Any], key: str) -> datetime | None:
    v = item.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise WtsError(f"{key}: expected an ISO 8601 string")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError as exc:
        raise WtsError(f"{key}: {exc}") from None
    if dt.tzinfo is None:
        raise WtsError(f"{key}: an offset is required")
    return dt.astimezone(UTC)


class JsonFileWtsSource:
    def __init__(self, path: Path, clock: Clock, *,
                 self_session_id: Callable[[], int] = current_session_id) -> None:
        self._path = path
        self._clock = clock
        self._self_session_id = self_session_id

    def snapshot(self) -> WtsSnapshot:
        try:
            doc = json.loads(self._path.read_text("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WtsError(f"{self._path}: {exc}") from None
        if not isinstance(doc, dict) or not isinstance(doc.get("sessions"), list):
            raise WtsError(f"{self._path}: expected {{\"sessions\": [...]}}")
        at = self._clock.now()
        sessions = []
        for i, item in enumerate(cast(list[Any], doc["sessions"])):
            try:
                sessions.append(self._session(item, at))
            except WtsError as exc:
                raise WtsError(f"{self._path}: sessions[{i}]: {exc}") from None
        return WtsSnapshot(at=at, sessions=tuple(sessions))

    def _session(self, item: Any, at: datetime) -> WtsSession:
        if not isinstance(item, dict):
            raise WtsError("expected an object")
        raw_id = item.get("session_id")
        if raw_id == "self":
            try:
                session_id = self._self_session_id()
            except RuntimeError as exc:
                raise WtsError(f"session_id \"self\": {exc}") from None
        elif isinstance(raw_id, int) and not isinstance(raw_id, bool) and raw_id >= 0:
            session_id = raw_id
        else:
            raise WtsError("session_id: expected a non-negative integer or \"self\"")
        user = item.get("user")
        if not isinstance(user, str):
            raise WtsError("user: required string")
        build = item.get("client_build")
        if build is not None and not _is_int(build):
            raise WtsError("client_build: expected an integer")
        idle = item.get("idle_sec")
        if idle is not None and not ((_is_int(idle) or isinstance(idle, float)) and idle >= 0):
            raise WtsError("idle_sec: expected a non-negative number")
        locked = item.get("locked")
        if locked is not None and not isinstance(locked, bool):
            raise WtsError("locked: expected true, false or null")
        state = item.get("state", "active")
        if state not in STATE_NAMES:
            raise WtsError(f"state: expected one of {', '.join(STATE_NAMES)}")
        protocol = item.get("protocol", "rdp")
        if protocol not in _PROTOCOLS:
            raise WtsError(f"protocol: expected one of {', '.join(_PROTOCOLS)}")
        return WtsSession(
            session_id=session_id,
            station=f"json-{session_id}",
            state=state,
            user=user,
            domain=_opt_str(item, "domain"),
            client_name=_opt_str(item, "client_name"),
            client_ip=_opt_str(item, "client_ip"),
            client_build=build,
            protocol=protocol,
            resolution=_opt_str(item, "resolution"),
            logon_at=_opt_dt(item, "logon_at"),
            connected_at=_opt_dt(item, "connected_at"),
            disconnected_at=_opt_dt(item, "disconnected_at"),
            last_input_at=None if idle is None else at - timedelta(seconds=idle),
            locked=locked,
        )
