"""Maps RDP-session event-log records (LSM, RCM, Security) to ``session`` log lines and stores
logon failures (4625) in ``rdp_logon_failures``.

``SessionEventHandler`` runs on the event-loop thread (``EventLogComponent`` dispatches there).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.logstore.writer import LogSink
from app.sessions.history import LogonFailureIn, SessionHistory
from app.win.eventlog import EventRecord

SECURITY_CHANNEL = "security"
LSM_CHANNEL = "microsoft-windows-terminalservices-localsessionmanager/operational"
RCM_CHANNEL = "microsoft-windows-terminalservices-remoteconnectionmanager/operational"

SESSION_EVENT_NAMES: dict[int, str] = {
    21: "lsm_logon", 22: "lsm_shell_start", 23: "lsm_logoff", 24: "lsm_disconnect",
    25: "lsm_reconnect", 1149: "rdp_auth_ok", 4624: "logon", 4625: "logon_failed",
    4634: "logoff", 4647: "user_logoff", 4778: "session_reconnect", 4779: "session_disconnect",
    4800: "lock", 4801: "unlock",
}

_REMOTE_LOGON_TYPES = (10, 7)  # RemoteInteractive, Unlock
_SERVICE_SIDS = ("S-1-5-18", "S-1-5-19", "S-1-5-20")  # SYSTEM, LocalService, NetworkService


@dataclass(frozen=True)
class SessionLogEvent:
    name: str
    at: datetime
    fields: dict[str, Any]
    failure: LogonFailureIn | None


def _text(data: Mapping[str, str | None], key: str) -> str | None:
    """The value, or ``None`` when it is missing, empty or ``-``."""
    value = data.get(key)
    if value is None:
        return None
    value = value.strip()
    return None if value in ("", "-") else value


def _int(data: Mapping[str, str | None], key: str) -> int | None:
    value = _text(data, key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _user(domain: str | None, name: str | None) -> str | None:
    """``DOMAIN\\name``, or just the name when there is no domain."""
    if name is None:
        return None
    return name if domain is None else f"{domain}\\{name}"


def _target_user(d: Mapping[str, str | None]) -> str | None:
    return _user(_text(d, "TargetDomainName"), _text(d, "TargetUserName"))


def _is_noise_account(d: Mapping[str, str | None]) -> bool:
    """A machine account (``NAME$``) or a built-in service SID."""
    name = _text(d, "TargetUserName")
    return (name is not None and name.endswith("$")) or _text(d, "TargetUserSid") in _SERVICE_SIDS


def _lsm(eid: int, d: Mapping[str, str | None]) -> dict[str, Any]:
    fields: dict[str, Any] = {"user": _text(d, "User"), "session_id": _int(d, "SessionID")}
    if eid != 23:  # the logoff event has no address
        address = _text(d, "Address")
        fields["client_ip"] = None if address is not None and address.upper() == "LOCAL" else address
    return fields


def _rcm(_eid: int, d: Mapping[str, str | None]) -> dict[str, Any]:
    return {"user": _user(_text(d, "Param2"), _text(d, "Param1")), "client_ip": _text(d, "Param3")}


def _logon(_eid: int, d: Mapping[str, str | None]) -> dict[str, Any] | None:
    logon_type = _int(d, "LogonType")
    if logon_type not in _REMOTE_LOGON_TYPES or _is_noise_account(d):
        return None
    return {
        "user": _target_user(d), "client_ip": _text(d, "IpAddress"),
        "workstation": _text(d, "WorkstationName"), "logon_type": logon_type,
        "logon_id": _text(d, "TargetLogonId"),
    }


def _logon_failed(_eid: int, d: Mapping[str, str | None]) -> dict[str, Any]:
    return {
        "user": _target_user(d), "client_ip": _text(d, "IpAddress"),
        "workstation": _text(d, "WorkstationName"), "logon_type": _int(d, "LogonType"),
        "status": _text(d, "Status"), "sub_status": _text(d, "SubStatus"),
    }


def _logoff(_eid: int, d: Mapping[str, str | None]) -> dict[str, Any] | None:
    logon_type = _int(d, "LogonType")
    if logon_type not in _REMOTE_LOGON_TYPES or _is_noise_account(d):
        return None
    return {"user": _target_user(d), "logon_type": logon_type, "logon_id": _text(d, "TargetLogonId")}


def _user_logoff(_eid: int, d: Mapping[str, str | None]) -> dict[str, Any]:
    return {"user": _target_user(d), "logon_id": _text(d, "TargetLogonId")}


def _session_change(_eid: int, d: Mapping[str, str | None]) -> dict[str, Any]:
    return {
        "user": _user(_text(d, "AccountDomain"), _text(d, "AccountName")),
        "client_name": _text(d, "ClientName"), "client_ip": _text(d, "ClientAddress"),
        "session_name": _text(d, "SessionName"), "logon_id": _text(d, "LogonID"),
    }


def _lock(_eid: int, d: Mapping[str, str | None]) -> dict[str, Any]:
    return {"user": _target_user(d), "session_id": _int(d, "SessionId")}


_Mapper = Callable[[int, Mapping[str, str | None]], dict[str, Any] | None]

_MAPPERS: dict[tuple[str, int], _Mapper] = {
    **{(LSM_CHANNEL, eid): _lsm for eid in (21, 22, 23, 24, 25)},
    (RCM_CHANNEL, 1149): _rcm,
    (SECURITY_CHANNEL, 4624): _logon,
    (SECURITY_CHANNEL, 4625): _logon_failed,
    (SECURITY_CHANNEL, 4634): _logoff,
    (SECURITY_CHANNEL, 4647): _user_logoff,
    (SECURITY_CHANNEL, 4778): _session_change,
    (SECURITY_CHANNEL, 4779): _session_change,
    (SECURITY_CHANNEL, 4800): _lock,
    (SECURITY_CHANNEL, 4801): _lock,
}


def map_session_record(r: EventRecord) -> SessionLogEvent | None:
    """A session event (``SESSION_EVENT_NAMES``) from its own channel → ``SessionLogEvent``;
    anything else, and filtered noise (non-remote logon types, machine/service accounts), → None.
    Missing, empty and ``-`` values become ``None``."""
    mapper = _MAPPERS.get((r.channel.lower(), r.event_id))
    if mapper is None:
        return None
    fields = mapper(r.event_id, r.data)
    if fields is None:
        return None
    failure = None
    if r.event_id == 4625:
        failure = LogonFailureIn(
            r.time_created, _text(r.data, "TargetUserName"), _text(r.data, "TargetDomainName"),
            fields["client_ip"], fields["workstation"], fields["logon_type"], fields["status"],
            fields["sub_status"], "eventlog:4625", r.record_id,
        )
    return SessionLogEvent(SESSION_EVENT_NAMES[r.event_id], r.time_created, fields, failure)


class SessionEventHandler:
    """``EventLogComponent`` handler for the security, LSM and RCM channels: one ``session`` log
    line per mapped record, stamped with the event time. A logon failure is stored first; one
    already stored (same ``(source, record_id)``, e.g. replayed after a lost bookmark) is
    neither stored nor logged again."""

    def __init__(self, history: SessionHistory, log: LogSink) -> None:
        self._history = history
        self._log = log

    def __call__(self, records: list[EventRecord]) -> None:
        for r in records:
            ev = map_session_record(r)
            if ev is None:
                continue
            if ev.failure is not None and self._history.add_failure(ev.failure) is None:
                continue
            self._log.emit(
                "session", at=ev.at, event=ev.name, event_id=r.event_id, record_id=r.record_id,
                source=f"eventlog:{r.event_id}", **ev.fields,
            )
