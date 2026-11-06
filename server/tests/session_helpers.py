"""Builders for WTS sessions and snapshots used by the session tracker tests."""

from __future__ import annotations

from datetime import UTC, datetime

from app.win.wts import WtsProtocol, WtsSession, WtsSnapshot

T0 = datetime(2026, 11, 4, 4, 0, tzinfo=UTC)  # 13:00 KST


def ws(
    session_id: int = 2,
    *,
    state: str = "active",
    user: str = "hong",
    domain: str | None = "CORP",
    protocol: WtsProtocol = "rdp",
    logon: datetime | None = T0,
    connected: datetime | None = T0,
    ip: str | None = "10.0.3.21",
    name: str | None = "HONG-LAPTOP",
    build: int | None = 26100,
    res: str | None = "1920x1080@32",
    locked: bool | None = False,
    last_input: datetime | None = None,
) -> WtsSession:
    return WtsSession(
        session_id=session_id,
        station=f"RDP-Tcp#{session_id}",
        state=state,
        user=user,
        domain=domain,
        client_name=name,
        client_ip=ip,
        client_build=build,
        protocol=protocol,
        resolution=res,
        logon_at=logon,
        connected_at=connected,
        disconnected_at=None,
        last_input_at=last_input,
        locked=locked,
    )


def snap(at: datetime, *sessions: WtsSession) -> WtsSnapshot:
    return WtsSnapshot(at=at, sessions=tuple(sessions))
