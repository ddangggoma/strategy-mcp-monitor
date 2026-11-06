import getpass
import os
import socket
import sys

import pytest

from app.win.ffi import current_session_id, process_session_id
from app.win.peer import PeerInfo, PsutilPeerResolver
from tests.test_auth_api import audit_events, bootstrap, login
from tests.winfakes import FakePeerResolver

windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows API")


@windows
def test_process_session_id_of_self_and_unknown_pid():
    sid = process_session_id(os.getpid())
    assert isinstance(sid, int) and sid >= 0 and current_session_id() == sid
    assert process_session_id(0xFFFFFFF0) is None


@windows
def test_real_resolver_finds_this_process_for_a_loopback_connection():
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen()
    cli = socket.create_connection(srv.getsockname()); conn, _ = srv.accept()
    try:
        info = PsutilPeerResolver().resolve("127.0.0.1", cli.getsockname()[1], srv.getsockname()[1])
        assert info is not None and info.pid == os.getpid() and info.session_id == current_session_id()
        assert info.user is not None and info.user.lower().endswith("\\" + getpass.getuser().lower())
        assert info.exe is not None and info.exe.lower().endswith("python.exe")
    finally:
        conn.close(); cli.close(); srv.close()


def test_resolver_ignores_non_loopback_and_unknown_connections():
    r = PsutilPeerResolver()
    assert r.resolve("10.0.0.1", 50000, 8700) is None
    assert r.resolve("127.0.0.1", 1, 2) is None


HONG = PeerInfo(pid=4242, session_id=2, user="CORP\\hong", exe=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


async def test_local_auth_events_record_the_windows_account(local_client, services):
    services.peers = FakePeerResolver(HONG)
    await bootstrap(local_client); await login(local_client, services)
    events = await audit_events(services, "auth")
    assert {e["event"] for e in events} >= {"otp_request", "login"}
    assert all(e["windows_user"] == "CORP\\hong" for e in events)
    assert services.peers.calls[0][0] == "127.0.0.1" and services.peers.calls[0][2] == 8700


async def test_external_auth_events_have_no_windows_account(local_client, external_client, services):
    services.peers = FakePeerResolver(HONG)
    await bootstrap(local_client); await login(external_client, services)
    ext = [e for e in await audit_events(services, "auth") if e["channel"] == "external"]
    assert ext and all("windows_user" not in e for e in ext)


async def test_unresolvable_peer_is_recorded_as_null(local_client, services):
    services.peers = FakePeerResolver(None)
    await bootstrap(local_client); await login(local_client, services)
    assert all(e["windows_user"] is None for e in await audit_events(services, "auth"))


# Beyond the plan's tests: the other local auth lines (failed login, 429, logout) and a resolver
# that raises.


async def test_failed_rate_limited_and_logout_lines_record_the_windows_account(local_client, services):
    services.peers = FakePeerResolver(HONG)
    await bootstrap(local_client); await login(local_client, services)
    code = services.otp.provider.sent[-1][1]
    wrong = "000000" if code != "000000" else "111111"
    r = await local_client.post("/api/auth/otp/verify", json={"email": "admin@x.com", "code": wrong})
    assert r.status_code == 401
    r = await local_client.post("/api/auth/otp/request", json={"email": "admin@x.com"})
    assert r.status_code == 429  # resend cooldown
    r = await local_client.post("/api/auth/logout", headers={"X-CSRF-Token": local_client.csrf})
    assert r.status_code == 204
    events = await audit_events(services, "auth")
    assert [(e["event"], e["ok"]) for e in events] == [
        ("otp_request", True), ("login", True), ("login", False), ("otp_request", False), ("logout", True),
    ]
    assert all(e["windows_user"] == "CORP\\hong" for e in events)


class _RaisingResolver:
    def resolve(self, client_ip, client_port, server_port):
        raise OSError("boom")


async def test_resolver_error_is_recorded_as_null(local_client, services):
    services.peers = _RaisingResolver()
    await bootstrap(local_client); await login(local_client, services)
    events = await audit_events(services, "auth")
    assert events and all(e["windows_user"] is None for e in events)


async def test_repeated_rate_limited_auth_requests_cost_no_peer_lookup(local_client, services):
    """M1: a client hammering the OTP routes while throttled gets no connection-table scan per
    request; the one audited 429 per window still records the Windows account."""
    services.peers = FakePeerResolver(HONG)
    await bootstrap(local_client); await login(local_client, services)
    before = len(services.peers.calls)
    for _ in range(5):
        r = await local_client.post("/api/auth/otp/request", json={"email": "admin@x.com"})
        assert r.status_code == 429
    assert len(services.peers.calls) == before + 1  # only for the audited (first) 429
    limited = [e for e in await audit_events(services, "auth") if e["event"] == "otp_request" and not e["ok"]]
    assert len(limited) == 1 and limited[0]["windows_user"] == "CORP\\hong"
