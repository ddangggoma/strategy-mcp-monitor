# server/tests/test_session_eventmap.py
from datetime import UTC, datetime, timedelta

import pytest

from app.sessions.eventmap import SESSION_EVENT_NAMES, SessionEventHandler, map_session_record
from app.sessions.history import LogonFailureIn
from app.win.eventlog import parse_event_xml
from tests.eventlog_helpers import evt_xml
from tests.test_auth_api import audit_events
from tests.winfakes import FakeEventLogSource, ListLog, eventually

SEC = "Security"; LSM = "Microsoft-Windows-TerminalServices-LocalSessionManager/Operational"
RCM = "Microsoft-Windows-TerminalServices-RemoteConnectionManager/Operational"

def rec(channel, eid, data=None, user_data=None, rid=1, time="2026-11-04T04:59:30Z"):
    return parse_event_xml(evt_xml(channel, eid, rid, time, data=data, user_data=user_data))

@pytest.mark.parametrize("record,name,fields", [
    (rec(LSM, 21, user_data=("EventXML", {"User": "CORP\\hong", "SessionID": "2", "Address": "10.0.3.21"})), "lsm_logon",
     {"user": "CORP\\hong", "session_id": 2, "client_ip": "10.0.3.21"}),
    (rec(LSM, 24, user_data=("EventXML", {"User": "CORP\\hong", "SessionID": "2", "Address": "LOCAL"})), "lsm_disconnect",
     {"user": "CORP\\hong", "session_id": 2, "client_ip": None}),
    (rec(RCM, 1149, user_data=("EventXML", {"Param1": "hong", "Param2": "CORP", "Param3": "10.0.3.21"})), "rdp_auth_ok",
     {"user": "CORP\\hong", "client_ip": "10.0.3.21"}),
    (rec(SEC, 4624, {"TargetUserName": "hong", "TargetDomainName": "CORP", "TargetUserSid": "S-1-5-21-1-2-3-1001", "LogonType": "10",
                     "IpAddress": "10.0.3.21", "WorkstationName": "HONG-LAPTOP", "TargetLogonId": "0x3e7a1"}), "logon",
     {"user": "CORP\\hong", "client_ip": "10.0.3.21", "workstation": "HONG-LAPTOP", "logon_type": 10, "logon_id": "0x3e7a1"}),
    (rec(SEC, 4778, {"AccountName": "hong", "AccountDomain": "CORP", "LogonID": "0x3e7a1", "SessionName": "RDP-Tcp#3",
                     "ClientName": "HONG-LAPTOP", "ClientAddress": "10.0.3.21"}), "session_reconnect",
     {"user": "CORP\\hong", "client_name": "HONG-LAPTOP", "client_ip": "10.0.3.21", "session_name": "RDP-Tcp#3", "logon_id": "0x3e7a1"}),
    (rec(SEC, 4800, {"TargetUserName": "hong", "TargetDomainName": "CORP", "SessionId": "2"}), "lock",
     {"user": "CORP\\hong", "session_id": 2}),
])
def test_maps_session_records(record, name, fields):
    ev = map_session_record(record)
    assert (ev.name, ev.fields, ev.failure, ev.at) == (name, fields, None, datetime(2026, 11, 4, 4, 59, 30, tzinfo=UTC))

@pytest.mark.parametrize("data", [
    {"TargetUserName": "svc", "TargetDomainName": "CORP", "TargetUserSid": "S-1-5-21-1", "LogonType": "3", "IpAddress": "-"},
    {"TargetUserName": "MCP-HOST$", "TargetDomainName": "CORP", "TargetUserSid": "S-1-5-21-2", "LogonType": "10"},
    {"TargetUserName": "SYSTEM", "TargetDomainName": "NT AUTHORITY", "TargetUserSid": "S-1-5-18", "LogonType": "7"},
])
def test_drops_noise_logons(data):
    assert map_session_record(rec(SEC, 4624, data)) is None

def test_unknown_ids_are_ignored():
    assert map_session_record(rec(SEC, 4720, {"TargetUserName": "x"})) is None

async def test_failures_are_stored_and_logged_with_event_time(services, clock):
    r = rec(SEC, 4625, {"TargetUserName": "hong", "TargetDomainName": "CORP", "LogonType": "3", "IpAddress": "203.0.113.9",
                        "WorkstationName": "EVIL", "Status": "0xc000006d", "SubStatus": "0xc000006a"}, rid=77)
    h = SessionEventHandler(services.rdp_history, services.log)
    h([r, r])  # a duplicate record id is stored once
    [f] = services.rdp_history.failures(clock.now() - timedelta(days=1))
    assert (f.user, f.domain, f.client_ip, f.workstation, f.logon_type, f.status, f.sub_status, f.source, f.record_id) == \
        ("hong", "CORP", "203.0.113.9", "EVIL", 3, "0xc000006d", "0xc000006a", "eventlog:4625", 77)
    lines = [e for e in await audit_events(services, "session") if e["event"] == "logon_failed"]
    assert len(lines) == 1  # preflight F19: the duplicate is neither stored nor logged again
    assert lines[0]["ts"] == "2026-11-04T13:59:30.000+09:00" and lines[0]["source"] == "eventlog:4625"

async def test_session_events_use_event_time(services):
    h = SessionEventHandler(services.rdp_history, services.log)
    h([rec(LSM, 25, user_data=("EventXML", {"User": "CORP\\hong", "SessionID": "2", "Address": "10.0.3.21"}),
           time="2026-11-03T14:59:59.9Z")])
    await services.log.flush()
    day = (services.paths.logs_dir / "2026-11-03.jsonl").read_text("utf-8")
    assert '"event": "lsm_reconnect"' in day and '"ts": "2026-11-03T23:59:59.900+09:00"' in day


# --- beyond the plan's tests: the rest of the mapping table, value cleanup and the wiring ---

LSM_USER = {"User": "CORP\\hong", "SessionID": "3", "Address": "10.0.3.22"}


@pytest.mark.parametrize("record,name,fields", [
    (rec(LSM, 22, user_data=("EventXML", LSM_USER)), "lsm_shell_start",
     {"user": "CORP\\hong", "session_id": 3, "client_ip": "10.0.3.22"}),
    (rec(LSM, 23, user_data=("EventXML", {"User": "CORP\\hong", "SessionID": "3"})), "lsm_logoff",
     {"user": "CORP\\hong", "session_id": 3}),
    (rec(LSM, 25, user_data=("EventXML", LSM_USER)), "lsm_reconnect",
     {"user": "CORP\\hong", "session_id": 3, "client_ip": "10.0.3.22"}),
    (rec(RCM, 1149, user_data=("EventXML", {"Param1": "hong", "Param2": "", "Param3": "10.0.3.21"})), "rdp_auth_ok",
     {"user": "hong", "client_ip": "10.0.3.21"}),
    (rec(SEC, 4624, {"TargetUserName": "hong", "TargetDomainName": "CORP", "TargetUserSid": "S-1-5-21-1-2-3-1001", "LogonType": "7",
                     "IpAddress": "-", "WorkstationName": "-", "TargetLogonId": "0x3e7b2"}), "logon",
     {"user": "CORP\\hong", "client_ip": None, "workstation": None, "logon_type": 7, "logon_id": "0x3e7b2"}),
    (rec(SEC, 4634, {"TargetUserName": "hong", "TargetDomainName": "CORP", "TargetUserSid": "S-1-5-21-1-2-3-1001",
                     "LogonType": "10", "TargetLogonId": "0x3e7a1"}), "logoff",
     {"user": "CORP\\hong", "logon_type": 10, "logon_id": "0x3e7a1"}),
    (rec(SEC, 4647, {"TargetUserName": "hong", "TargetDomainName": "CORP", "TargetLogonId": "0x3e7a1"}), "user_logoff",
     {"user": "CORP\\hong", "logon_id": "0x3e7a1"}),
    (rec(SEC, 4779, {"AccountName": "hong", "AccountDomain": "CORP", "LogonID": "0x3e7a1", "SessionName": "RDP-Tcp#3",
                     "ClientName": "HONG-LAPTOP", "ClientAddress": "10.0.3.21"}), "session_disconnect",
     {"user": "CORP\\hong", "client_name": "HONG-LAPTOP", "client_ip": "10.0.3.21", "session_name": "RDP-Tcp#3", "logon_id": "0x3e7a1"}),
    (rec(SEC, 4801, {"TargetUserName": "hong", "TargetDomainName": "", "SessionId": "2"}), "unlock",
     {"user": "hong", "session_id": 2}),
])
def test_maps_the_rest_of_the_table(record, name, fields):
    ev = map_session_record(record)
    assert (ev.name, ev.fields, ev.failure) == (name, fields, None)
    assert SESSION_EVENT_NAMES[record.event_id] == name


def test_event_name_table_is_the_plans():
    assert SESSION_EVENT_NAMES == {
        21: "lsm_logon", 22: "lsm_shell_start", 23: "lsm_logoff", 24: "lsm_disconnect", 25: "lsm_reconnect",
        1149: "rdp_auth_ok", 4624: "logon", 4625: "logon_failed", 4634: "logoff", 4647: "user_logoff",
        4778: "session_reconnect", 4779: "session_disconnect", 4800: "lock", 4801: "unlock"}


def test_failure_maps_every_logon_type_with_blank_values_as_none():
    r = rec(SEC, 4625, {"TargetUserName": "admin", "TargetDomainName": "-", "LogonType": "10", "IpAddress": "-",
                        "WorkstationName": "", "Status": "0xc000006d", "SubStatus": "0xc0000064"}, rid=9)
    ev = map_session_record(r)
    assert ev.name == "logon_failed"
    assert ev.fields == {"user": "admin", "client_ip": None, "workstation": None, "logon_type": 10,
                         "status": "0xc000006d", "sub_status": "0xc0000064"}
    assert ev.failure == LogonFailureIn(r.time_created, "admin", None, None, None, 10, "0xc000006d", "0xc0000064",
                                        "eventlog:4625", 9)


@pytest.mark.parametrize("data", [
    {"TargetUserName": "hong", "TargetDomainName": "CORP", "TargetUserSid": "S-1-5-21-1", "LogonType": "2", "TargetLogonId": "0x1"},
    {"TargetUserName": "MCP-HOST$", "TargetDomainName": "CORP", "TargetUserSid": "S-1-5-21-2", "LogonType": "10", "TargetLogonId": "0x2"},
    {"TargetUserName": "LOCAL SERVICE", "TargetDomainName": "NT AUTHORITY", "TargetUserSid": "S-1-5-19", "LogonType": "7"},
])
def test_drops_noise_logoffs(data):
    assert map_session_record(rec(SEC, 4634, data)) is None


@pytest.mark.parametrize("sid", ["S-1-5-19", "S-1-5-20"])
def test_drops_service_account_logons(sid):
    assert map_session_record(rec(SEC, 4624, {"TargetUserName": "svc", "TargetDomainName": "NT AUTHORITY",
                                              "TargetUserSid": sid, "LogonType": "10"})) is None


@pytest.mark.parametrize("record", [
    rec(SEC, 21, {"User": "CORP\\hong"}),                                               # an LSM id on the wrong channel
    rec(LSM, 4624, user_data=("EventXML", {"User": "CORP\\hong"})),
    rec(RCM, 1148, user_data=("EventXML", {"Param1": "hong"})),
    rec("System", 4800, {"TargetUserName": "hong"}),
])
def test_ids_on_other_channels_are_ignored(record):
    assert map_session_record(record) is None


def test_bad_numbers_and_missing_values_become_none():
    ev = map_session_record(rec(LSM, 21, user_data=("EventXML", {"User": None, "SessionID": "x", "Address": "-"})))
    assert ev.fields == {"user": None, "session_id": None, "client_ip": None}
    ev = map_session_record(rec(SEC, 4625, {"TargetUserName": "-", "LogonType": "?"}))
    assert ev.fields["user"] is None and ev.fields["logon_type"] is None and ev.failure.user is None


def test_handler_logs_each_mapped_record_and_skips_the_rest(services):
    log = ListLog()
    h = SessionEventHandler(services.rdp_history, log)
    lock = rec(SEC, 4800, {"TargetUserName": "hong", "TargetDomainName": "CORP", "SessionId": "2"}, rid=5)
    h([rec(SEC, 4688, {"NewProcessName": "C:\\x.exe"}, rid=4), lock])
    assert log.events == [("session", lock.time_created, {
        "event": "lock", "event_id": 4800, "record_id": 5, "source": "eventlog:4800", "user": "CORP\\hong", "session_id": 2})]
    assert services.rdp_history.failures(lock.time_created - timedelta(days=1)) == []


async def test_build_services_registers_the_handler_on_the_three_session_channels(tmp_path, clock):
    from app.collect.config import CollectorConfig
    from app.services import build_services
    from tests.fakes import CapturingOtpProvider, FakeProber, FakeRunner
    src = FakeEventLogSource()
    src.queue(LSM, [evt_xml(LSM, 21, 11, "2026-11-04T04:59:10Z", user_data=("EventXML", LSM_USER))])
    src.queue(RCM, [evt_xml(RCM, 1149, 12, "2026-11-04T04:59:05Z",
                            user_data=("EventXML", {"Param1": "hong", "Param2": "CORP", "Param3": "10.0.3.22"}))])
    src.queue(SEC, [evt_xml(SEC, 4625, 13, "2026-11-04T04:59:20Z",
                            data={"TargetUserName": "hong", "TargetDomainName": "CORP", "LogonType": "10", "IpAddress": "10.0.3.22"})])
    svc = build_services(tmp_path, clock=clock, otp_provider=CapturingOtpProvider(), runner=FakeRunner(),
                         prober=FakeProber(clock), collectors=CollectorConfig(event_log=src))
    seen = []  # registered after the session handler, so it runs after it for each batch
    for name in ("eventlog:security", "eventlog:lsm", "eventlog:rcm"):
        svc.eventlog.on(name, seen.extend)
    await svc.log.start()
    try:
        await svc.collectors.start()
        try:
            await eventually(lambda: len(seen) == 3)
            # plus the two PowerShell channels of the script-block handler (Task 10, activity on)
            assert sorted(o[0] for o in src.opened) == sorted([
                SEC, LSM, RCM, "Microsoft-Windows-PowerShell/Operational", "PowerShellCore/Operational"])
        finally:
            await svc.collectors.stop()
        assert [f.record_id for f in svc.rdp_history.failures(clock.now() - timedelta(days=1))] == [13]
        lines = await audit_events(svc, "session")
        assert sorted((e["event"], e["source"], e["record_id"], e["user"]) for e in lines) == [
            ("logon_failed", "eventlog:4625", 13, "CORP\\hong"), ("lsm_logon", "eventlog:21", 11, "CORP\\hong"),
            ("rdp_auth_ok", "eventlog:1149", 12, "CORP\\hong")]
    finally:
        await svc.log.stop()
        svc.db.close()
