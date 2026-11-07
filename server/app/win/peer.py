"""Map a loopback TCP peer (a request to the Local channel) to its Windows process and session."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Protocol

import psutil

from app.win.ffi import process_session_id


@dataclass(frozen=True)
class PeerInfo:
    pid: int
    session_id: int | None
    user: str | None  # DOMAIN\name, as psutil reports it
    exe: str | None


class PeerResolver(Protocol):
    def resolve(self, client_ip: str, client_port: int, server_port: int) -> PeerInfo | None: ...


def _is_loopback(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


class PsutilPeerResolver:
    """Finds the process owning the client end of a loopback connection (blocking: call off-loop)."""

    def resolve(self, client_ip: str, client_port: int, server_port: int) -> PeerInfo | None:
        if not _is_loopback(client_ip):
            return None
        pid = self._find_pid(client_port, server_port)
        if not pid:
            return None
        user: str | None = None
        exe: str | None = None
        try:
            proc = psutil.Process(pid)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            proc = None
        if proc is not None:
            try:
                user = proc.username()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                user = None
            try:
                exe = proc.exe() or None
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                exe = None
        return PeerInfo(pid=pid, session_id=process_session_id(pid), user=user, exe=exe)

    @staticmethod
    def _find_pid(client_port: int, server_port: int) -> int | None:
        for conn in psutil.net_connections("tcp"):
            laddr, raddr = conn.laddr, conn.raddr
            if not laddr or not raddr:
                continue
            if laddr.port != client_port or raddr.port != server_port:
                continue
            if not _is_loopback(laddr.ip):
                continue
            return conn.pid or None
        return None
