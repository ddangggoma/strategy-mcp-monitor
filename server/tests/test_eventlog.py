import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.collect.eventlog import (
    CHANNELS,
    BookmarkStore,
    ChannelSpec,
    ChannelWatcher,
    EventLogComponent,
    xpath_for,
)
from app.collect.manager import Collectors
from app.win.eventlog import EventLogError, PywinEventLogSource, parse_event_xml
from tests.eventlog_helpers import evt_xml
from tests.winfakes import FakeEventLogSource, ListLog, eventually

FIX = Path(__file__).parent / "fixtures" / "events"

def test_parse_security_4688_fixture():
    r = parse_event_xml((FIX / "security-4688.xml").read_text("utf-8"))
    assert (r.channel, r.provider, r.event_id, r.record_id, r.pid, r.computer) == \
        ("Security", "Microsoft-Windows-Security-Auditing", 4688, 91234, 4, "MCP-HOST")
    assert r.time_created == datetime(2026, 11, 4, 5, 3, 22, 418123, tzinfo=UTC)
    assert (r.data["NewProcessId"], r.data["CommandLine"], r.data["SubjectUserName"]) == ("0x2274", "cmd.exe /c deploy.bat", "hong")

def test_parse_lsm_userdata_fixture():
    r = parse_event_xml((FIX / "lsm-25.xml").read_text("utf-8"))
    assert (r.event_id, r.user_sid, dict(r.data)) == (25, "S-1-5-18", {"User": "CORP\\hong", "SessionID": "2", "Address": "10.0.3.21", "SessionReason": "0"})

def test_parse_builder_round_trip_and_unnamed_data():
    r = parse_event_xml(evt_xml("System", 104, 7, provider="Microsoft-Windows-Eventlog", user_data=("LogFileCleared", {"SubjectUserName": "admin", "Channel": "Application"})))
    assert (r.channel, r.event_id, r.data["Channel"]) == ("System", 104, "Application")

@pytest.mark.parametrize("bad", ["", "<Event>", "<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System/></Event>"])
def test_parse_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_event_xml(bad)

def test_xpath_and_channel_table():
    assert xpath_for([21, 25]) == "*[System[(EventID=21 or EventID=25)]]"
    assert {c.name for c in CHANNELS} == {"eventlog:security", "eventlog:lsm", "eventlog:rcm", "eventlog:powershell", "eventlog:pwsh", "eventlog:system"}

def test_bookmark_store_roundtrip_and_corrupt(tmp_path, capsys):
    p = tmp_path / "state.json"; b = BookmarkStore(p); b.set("Security", 10); b.set("System", 3)
    assert BookmarkStore(p).get("Security") == 10 and json.loads(p.read_text("utf-8")) == {"Security": 10, "System": 3}
    p.write_text("{", "utf-8")
    assert BookmarkStore(p).get("Security") is None
    assert "corrupt bookmark file" in capsys.readouterr().err

LSM = ChannelSpec("eventlog:lsm", "LSM", (21, 25))
NOW = datetime(2026, 11, 4, 5, 0, tzinfo=UTC)

def watcher(src, records, statuses, tmp_path, **kw):
    return ChannelWatcher(LSM, src, records.append, statuses.append, BookmarkStore(tmp_path / "b.json"), now=lambda: NOW, **kw)

async def test_watcher_posts_records_and_saves_bookmark(tmp_path):
    src = FakeEventLogSource(); src.latest["LSM"] = 500
    src.queue("LSM", [evt_xml("LSM", 25, 501, "2026-11-04T04:59:59Z"), "<broken", evt_xml("LSM", 21, 502, "2026-11-04T04:59:59.5Z")])
    records, statuses = [], []
    w = watcher(src, records, statuses, tmp_path, save_every_sec=0); w.start()
    try:
        await eventually(lambda: len(records) == 2)
    finally:
        w.stop()
    assert src.opened == [("LSM", "*[System[(EventID=21 or EventID=25)]]", 500)]
    assert [r.record_id for r in records] == [501, 502] and statuses[0] == ("eventlog:lsm", True, None)
    assert BookmarkStore(tmp_path / "b.json").get("LSM") == 502

async def test_watcher_reports_access_denied_and_retries(tmp_path):
    src = FakeEventLogSource(); err = EventLogError("access denied"); err.access_denied = True
    src.fail_open("LSM", err)
    records, statuses = [], []
    w = watcher(src, records, statuses, tmp_path, retry_sec=0.05); w.start()
    try:
        await eventually(lambda: len(statuses) >= 2)
    finally:
        w.stop()
    assert statuses[0] == ("eventlog:lsm", False, "access denied") and statuses[1] == ("eventlog:lsm", True, None)

async def test_watcher_resumes_after_bookmark_and_drops_old_events(tmp_path):
    BookmarkStore(tmp_path / "b.json").set("LSM", 40)
    src = FakeEventLogSource()
    src.queue("LSM", [evt_xml("LSM", 25, 41, "2026-11-02T00:00:00Z"), evt_xml("LSM", 25, 42, "2026-11-04T04:00:00Z")])
    records, statuses = [], []
    w = watcher(src, records, statuses, tmp_path); w.start()
    try:
        await eventually(lambda: len(records) == 1)
    finally:
        w.stop()
    assert src.opened[0][2] == 40 and records[0].record_id == 42

async def test_component_dispatches_on_the_loop_and_skips_unhandled(services, clock, tmp_path):
    src = FakeEventLogSource(); src.latest["LSM"] = 1
    src.queue("LSM", [evt_xml("LSM", 25, 2, "2026-11-04T04:59:59Z")])
    comp = EventLogComponent(src, BookmarkStore(tmp_path / "b.json"), services.collectors, clock,
                             specs=(LSM, ChannelSpec("eventlog:rcm", "RCM", (1149,))))
    got = []; comp.on("eventlog:lsm", got.extend)
    services.collectors.add(comp); await services.collectors.start()
    try:
        await eventually(lambda: len(got) == 1)
    finally:
        await services.collectors.stop()
    assert [o[0] for o in src.opened] == ["LSM"]
    assert [(s.name, s.ok) for s in services.collectors.status()] == [("eventlog:lsm", True)]

@pytest.mark.winlive
def test_pywin_source_reads_recent_system_events():
    src = PywinEventLogSource(); last = src.latest_record_id("System")
    assert isinstance(last, int) and last > 3
    sub = src.open("System", "*", last - 3)
    try:
        xs = sub.next(2000)
    finally:
        sub.close()
    recs = [parse_event_xml(x) for x in xs]
    assert 1 <= len(recs) <= 3 and all(r.channel == "System" and r.record_id > last - 3 for r in recs)
    with pytest.raises(EventLogError) as e:
        src.open("Security", "*", None)
    assert e.value.access_denied


# --- beyond the plan's tests ----------------------------------------------------------------

def test_parse_unnamed_and_empty_data_and_optional_system_parts():
    xml = ("<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System>"
           "<Provider Name='EventLog'/><EventID Qualifiers='32768'>6013</EventID>"
           "<TimeCreated SystemTime='2026-11-06T03:00:01Z'/><EventRecordID>67124</EventRecordID>"
           "<Channel>System</Channel></System>"
           "<EventData><Data></Data><Data>1967063</Data><Data Name='Note'/></EventData></Event>")
    r = parse_event_xml(xml)
    assert (r.event_id, r.record_id, r.pid, r.tid, r.user_sid, r.computer) == (6013, 67124, None, None, None, None)
    assert r.time_created == datetime(2026, 11, 6, 3, 0, 1, tzinfo=UTC)
    assert dict(r.data) == {"Data0": None, "Data1": "1967063", "Note": None}

def test_parse_builder_sets_execution_and_security_and_empty_user_data_children():
    r = parse_event_xml(evt_xml("LSM", 21, 9, "2026-11-04T05:00:00.5Z", pid=1080, user_sid="S-1-5-18",
                                user_data=("EventXML", {"User": "CORP\\kim", "Address": None})))
    assert (r.pid, r.tid, r.user_sid, r.computer) == (1080, 1180, "S-1-5-18", "MCP-HOST")
    assert r.time_created == datetime(2026, 11, 4, 5, 0, 0, 500000, tzinfo=UTC)
    assert dict(r.data) == {"User": "CORP\\kim", "Address": None}

def test_parse_data_is_read_only():
    r = parse_event_xml(evt_xml("Security", 4624, 1, data={"LogonType": "10"}))
    with pytest.raises(TypeError):
        r.data["LogonType"] = "2"  # type: ignore[index]

@pytest.mark.parametrize("xml", [
    evt_xml("S", 1, 1).replace("<EventRecordID>1</EventRecordID>", ""),
    evt_xml("S", 1, 1).replace("<EventID>1</EventID>", "<EventID>x</EventID>"),
    evt_xml("S", 1, 1, "yesterday"),
    evt_xml("S", 1, 1).replace("<Channel>S</Channel>", ""),
    evt_xml("S", 1, 1).replace("http://schemas.microsoft.com/win/2004/08/events/event", "urn:other"),
])
def test_parse_rejects_missing_or_invalid_required_parts(xml):
    with pytest.raises(ValueError):
        parse_event_xml(xml)

def test_xpath_needs_ids_and_the_channel_table_matches_the_plan():
    with pytest.raises(ValueError):
        xpath_for([])
    table = {c.name: (c.channel, c.event_ids) for c in CHANNELS}
    assert table["eventlog:security"] == ("Security", (1102, 4624, 4625, 4634, 4647, 4688, 4719, 4778, 4779, 4800, 4801))
    assert table["eventlog:lsm"] == ("Microsoft-Windows-TerminalServices-LocalSessionManager/Operational", (21, 22, 23, 24, 25))
    assert table["eventlog:rcm"] == ("Microsoft-Windows-TerminalServices-RemoteConnectionManager/Operational", (1149,))
    assert table["eventlog:powershell"] == ("Microsoft-Windows-PowerShell/Operational", (4104,))
    assert table["eventlog:pwsh"] == ("PowerShellCore/Operational", (4104,))
    assert table["eventlog:system"] == ("System", (104,))

def test_bookmark_store_missing_file_is_silent_and_writes_atomically(tmp_path, capsys):
    p = tmp_path / "data" / "collector-state.json"
    b = BookmarkStore(p)
    assert b.get("System") is None and capsys.readouterr().err == ""
    b.set("System", 5)
    assert json.loads(p.read_text("utf-8")) == {"System": 5}
    assert not p.with_suffix(".tmp").exists()

@pytest.mark.parametrize("content", ["[1, 2]", '{"System": "5"}', '{"System": true}'])
def test_bookmark_store_wrong_shape_counts_as_corrupt(tmp_path, capsys, content):
    p = tmp_path / "state.json"; p.write_text(content, "utf-8")
    b = BookmarkStore(p)
    assert b.get("System") is None
    assert capsys.readouterr().err.count("collector-state: corrupt bookmark file, starting fresh") == 1
    b.set("System", 6)
    assert json.loads(p.read_text("utf-8")) == {"System": 6}

def test_bookmark_store_concurrent_sets_keep_every_channel(tmp_path):
    p = tmp_path / "state.json"; b = BookmarkStore(p)
    threads = [threading.Thread(target=lambda c=c: [b.set(f"C{c}", i) for i in range(20)]) for c in range(6)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert json.loads(p.read_text("utf-8")) == {f"C{c}": 19 for c in range(6)}

async def test_watcher_saves_the_starting_point_when_nothing_arrives(tmp_path):
    src = FakeEventLogSource(); src.latest["LSM"] = 77
    records, statuses = [], []
    w = watcher(src, records, statuses, tmp_path); w.start()
    try:
        await eventually(lambda: len(statuses) == 1)
    finally:
        w.stop()
    assert records == [] and BookmarkStore(tmp_path / "b.json").get("LSM") == 77

async def test_watcher_reopens_after_its_last_record_when_the_subscription_fails(tmp_path):
    src = FakeEventLogSource(); src.latest["LSM"] = 10
    src.queue("LSM", [evt_xml("LSM", 25, 11, "2026-11-04T04:59:00Z")], EventLogError("subscription lost"),
              [evt_xml("LSM", 25, 12, "2026-11-04T04:59:30Z")])
    records, statuses = [], []
    w = watcher(src, records, statuses, tmp_path, retry_sec=0.01); w.start()
    try:
        await eventually(lambda: len(records) == 2)
    finally:
        w.stop()
    assert [o[2] for o in src.opened] == [10, 11]
    assert statuses == [("eventlog:lsm", True, None), ("eventlog:lsm", False, "subscription lost"), ("eventlog:lsm", True, None)]
    assert BookmarkStore(tmp_path / "b.json").get("LSM") == 12

async def test_watcher_counts_unparsable_events_and_still_advances(tmp_path):
    src = FakeEventLogSource(); src.latest["LSM"] = 1
    src.queue("LSM", ["<nope", "", evt_xml("LSM", 21, 2, "2026-11-04T04:59:00Z")])
    records, statuses = [], []
    w = watcher(src, records, statuses, tmp_path); w.start()
    try:
        await eventually(lambda: len(records) == 1)
    finally:
        w.stop()
    assert w.parse_errors == 2 and not w.alive

async def test_watcher_stop_during_retry_wait_returns_promptly(tmp_path):
    src = FakeEventLogSource(); src.fail_open("LSM", EventLogError("nope"))
    records, statuses = [], []
    w = watcher(src, records, statuses, tmp_path, retry_sec=60); w.start()
    await eventually(lambda: len(statuses) == 1)
    loop = asyncio.get_running_loop(); started = loop.time()
    await asyncio.to_thread(w.stop)
    assert loop.time() - started < 1.0 and not w.alive and src.opened == []

def test_component_rejects_unknown_channels(tmp_path, clock):
    comp = EventLogComponent(FakeEventLogSource(), BookmarkStore(tmp_path / "b.json"), Collectors(ListLog(), clock), clock,
                             specs=(LSM,))
    with pytest.raises(ValueError):
        comp.on("eventlog:nope", lambda items: None)
    assert comp.name == "eventlog"

async def test_component_reports_channel_failures_and_isolates_handler_errors(tmp_path, clock):
    log = ListLog(); collectors = Collectors(log, clock)
    src = FakeEventLogSource(); src.latest["LSM"] = 1
    denied = EventLogError("EvtSubscribe: access denied (5)", access_denied=True)
    src.fail_open("SEC", *([denied] * 50))
    src.queue("LSM", [evt_xml("LSM", 25, 2, "2026-11-04T04:59:59Z")])
    comp = EventLogComponent(src, BookmarkStore(tmp_path / "b.json"), collectors, clock,
                             specs=(LSM, ChannelSpec("eventlog:security", "SEC", (4624,))))
    got = []

    def boom(items):
        raise RuntimeError("handler bug")

    comp.on("eventlog:lsm", boom); comp.on("eventlog:lsm", got.extend); comp.on("eventlog:security", got.extend)
    collectors.add(comp); await collectors.start()
    try:
        await eventually(lambda: len(got) == 1 and len(collectors.status()) == 2)
        with pytest.raises(RuntimeError):
            comp.on("eventlog:lsm", got.extend)
    finally:
        await collectors.stop()
    assert [(s.name, s.ok, s.error) for s in collectors.status()] == [
        ("eventlog:lsm", True, None), ("eventlog:security", False, "EvtSubscribe: access denied (5)")]
    failed = [f for c, _, f in log.events if f.get("event") == "collector.handler_failed"]
    assert failed == [{"event": "collector.handler_failed", "source": "eventlog:lsm", "error": "RuntimeError('handler bug')"}]
    assert not any(t.name.startswith("eventlog:") for t in threading.enumerate())

async def test_component_without_handlers_starts_no_threads(tmp_path, clock):
    collectors = Collectors(ListLog(), clock); src = FakeEventLogSource()
    collectors.add(EventLogComponent(src, BookmarkStore(tmp_path / "b.json"), collectors, clock))
    await collectors.start()
    try:
        await asyncio.sleep(0.05)
        assert src.opened == [] and collectors.status() == []
        assert not any(t.name.startswith("eventlog:") for t in threading.enumerate())
    finally:
        await collectors.stop()

def test_event_log_error_flags():
    e = EventLogError("x")
    assert (str(e), e.access_denied, e.channel_missing) == ("x", False, False)
    assert EventLogError("y", channel_missing=True).channel_missing

def test_older_than_max_age_uses_the_given_clock():
    spec = ChannelSpec("eventlog:system", "System", (104,))
    w = ChannelWatcher(spec, FakeEventLogSource(), lambda r: None, lambda s: None, BookmarkStore(Path("unused.json")),
                       now=lambda: NOW, max_age=timedelta(hours=1))
    assert w.too_old(parse_event_xml(evt_xml("System", 104, 1, "2026-11-04T03:59:59Z")))
    assert not w.too_old(parse_event_xml(evt_xml("System", 104, 1, "2026-11-04T04:00:00Z")))

@pytest.mark.winlive
def test_pywin_source_next_after_drain_waits_and_returns_empty_and_reports_missing_channel():
    src = PywinEventLogSource(); last = src.latest_record_id("System")
    sub = src.open("System", "*[System[(EventID=999999)]]", last)
    try:
        assert sub.next(50) == [] and sub.next(50) == []
    finally:
        sub.close(); sub.close()
    with pytest.raises(EventLogError) as e:
        src.latest_record_id("PowerShellCore/Operational")
    assert e.value.channel_missing and not e.value.access_denied

@pytest.mark.winlive
def test_sid_to_account_resolves_well_known_and_rejects_bad_sids():
    from app.win.accounts import sid_to_account
    assert sid_to_account("S-1-5-18") == "NT AUTHORITY\\SYSTEM"
    assert sid_to_account("bogus") is None
    assert sid_to_account("S-1-5-21-1-2-3-99999") is None

@pytest.mark.parametrize("custom", [False, True])
async def test_build_services_adds_the_event_log_component_only_with_a_source(tmp_path, clock, custom):
    from app.collect.config import CollectorConfig
    from app.services import build_services
    from tests.fakes import CapturingOtpProvider, FakeProber, FakeRunner
    src = FakeEventLogSource(); src.latest["System"] = 3
    src.queue("System", [evt_xml("System", 104, 4, "2026-11-04T04:59:00Z", provider="Microsoft-Windows-Eventlog")])
    path = tmp_path / "elsewhere" / "marks.json" if custom else None
    kw = dict(clock=clock, otp_provider=CapturingOtpProvider(), runner=FakeRunner(), prober=FakeProber(clock))
    plain = build_services(tmp_path / "plain", **kw)
    assert plain.eventlog is None; plain.db.close()
    svc = build_services(tmp_path / "root", collectors=CollectorConfig(event_log=src, bookmarks_path=path), **kw)
    await svc.log.start()
    try:
        got = []; svc.eventlog.on("eventlog:system", got.extend)
        await svc.collectors.start()
        try:
            await eventually(lambda: len(got) == 1)
        finally:
            await svc.collectors.stop()
        expected = path if custom else svc.paths.data_dir / "collector-state.json"
        assert json.loads(expected.read_text("utf-8")) == {"System": 4}
        # System via the test's handler and the tamper handler (Task 14); Security/LSM/RCM via the
        # session handler (Task 8); the two PowerShell channels via the script-block handler (Task 10)
        assert sorted(o[0] for o in src.opened) == sorted([
            "System", "Security", "Microsoft-Windows-TerminalServices-LocalSessionManager/Operational",
            "Microsoft-Windows-TerminalServices-RemoteConnectionManager/Operational",
            "Microsoft-Windows-PowerShell/Operational", "PowerShellCore/Operational"])
    finally:
        await svc.log.stop()
        svc.db.close()
