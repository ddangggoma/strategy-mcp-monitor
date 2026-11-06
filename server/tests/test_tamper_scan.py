import asyncio
import json

import pytest

from app.activity.tamper import (
    AUDIT_REGISTRY,
    RegistryValue,
    TamperEventHandler,
    TamperScanner,
    map_tamper_record,
    read_hklm,
    scan_every,
)
from app.win.eventlog import parse_event_xml
from tests.eventlog_helpers import evt_xml
from tests.mcp_helpers import make_user, seed_mcp
from tests.test_auth_api import audit_events
from tests.winfakes import FakeEventLogSource, eventually

SUBJ = {"SubjectUserSid": "S-1-5-21-1", "SubjectUserName": "admin", "SubjectDomainName": "MCP-HOST", "SubjectLogonId": "0x1"}

def test_audit_policy_event_maps():
    r = parse_event_xml(evt_xml("Security", 4719, 5, data={**SUBJ, "CategoryId": "%%8274", "SubcategoryGuid": "{0CCE922B-69AE-11D9-BED3-505054503030}", "AuditPolicyChanges": "%%8448"}))
    assert map_tamper_record(r) == ("audit_policy_changed", {"user": "MCP-HOST\\admin", "category": "%%8274",
        "subcategory": "{0CCE922B-69AE-11D9-BED3-505054503030}", "changes": "%%8448"})

def test_log_cleared_events_map():
    sec = parse_event_xml(evt_xml("Security", 1102, 6, provider="Microsoft-Windows-Eventlog", user_data=("LogFileCleared", SUBJ)))
    sysr = parse_event_xml(evt_xml("System", 104, 7, provider="Microsoft-Windows-Eventlog", user_data=("LogFileCleared", {**SUBJ, "Channel": "Application"})))
    assert map_tamper_record(sec) == ("log_cleared", {"channel": "Security", "user": "MCP-HOST\\admin"})
    assert map_tamper_record(sysr) == ("log_cleared", {"channel": "Application", "user": "MCP-HOST\\admin"})
    assert map_tamper_record(parse_event_xml(evt_xml("Security", 4688, 8, data=SUBJ))) is None

def test_other_providers_and_missing_domain():
    # System 104 from another provider is not a cleared log; a user without a domain is the name alone
    other = parse_event_xml(evt_xml("System", 104, 9, provider="Service Control Manager", data={"param1": "x"}))
    assert map_tamper_record(other) is None
    nodomain = parse_event_xml(evt_xml("System", 104, 10, provider="Microsoft-Windows-Eventlog",
                                       user_data=("LogFileCleared", {"SubjectUserName": "admin", "Channel": "Setup"})))
    assert map_tamper_record(nodomain) == ("log_cleared", {"channel": "Setup", "user": "admin"})

async def test_handler_reports_with_event_time(services):
    TamperEventHandler(services.tamper)([parse_event_xml(evt_xml("Security", 1102, 6, "2026-11-04T04:00:00Z", provider="Microsoft-Windows-Eventlog", user_data=("LogFileCleared", SUBJ)))])
    rec = services.tamper.recent(1)[0]
    assert (rec["event"], rec["at"], rec["source"], rec["record_id"]) == ("log_cleared", "2026-11-04T13:00:00.000+09:00", "eventlog:1102", 6)

def scanner(services, values):
    return TamperScanner(services.tamper, services.scripts, services.mcps, services.paths.logs_dir, services.log,
                         read_value=lambda v: values[v.name], registry=(RegistryValue("A", "cmd"), RegistryValue("B", "ps")))

async def test_registry_baseline_then_change_reported_once(services):
    values = {"cmd": 1, "ps": None}; s = scanner(services, values)
    s.scan(); assert services.tamper.recent() == []
    assert [e["values"] for e in await audit_events(services, "system") if e.get("event") == "audit.config"] == [{"A\\cmd": 1, "B\\ps": None}]
    values["cmd"] = 0; s.scan(); s.scan()
    [rec] = services.tamper.recent()
    assert (rec["event"], rec["key"], rec["before"], rec["after"]) == ("audit_config_changed", "A\\cmd", 1, 0)

async def test_unreadable_registry_counts_as_missing(services):
    def boom(v):
        raise OSError(5, "denied")
    s = TamperScanner(services.tamper, services.scripts, services.mcps, services.paths.logs_dir, services.log, read_value=boom)
    s.scan(); s.scan()
    assert services.tamper.recent() == []
    [values] = [e["values"] for e in await audit_events(services, "system") if e.get("event") == "audit.config"]
    assert values == {f"{v.path}\\{v.name}": None for v in AUDIT_REGISTRY}

async def test_script_file_changed_and_missing_reported_once_until_fixed(services):
    m = seed_mcp(services, make_user(services, "o@x.com")); info = services.scripts.get(m.id, "start")
    s = scanner(services, {"cmd": None, "ps": None}); s.scan()
    original = info.path.read_bytes()
    info.path.write_bytes(b"exit /b 1"); s.scan(); s.scan()
    assert [r["event"] for r in services.tamper.recent()] == ["script_file_changed"]
    info.path.write_bytes(original); s.scan()
    info.path.write_bytes(b"exit /b 2"); s.scan()
    info.path.unlink(); s.scan()
    assert [r["event"] for r in services.tamper.recent()] == ["script_file_missing", "script_file_changed", "script_file_changed"]

async def test_script_report_fields(services):
    import hashlib
    m = seed_mcp(services, make_user(services, "o@x.com")); info = services.scripts.get(m.id, "start")
    s = scanner(services, {"cmd": None, "ps": None}); s.scan()
    info.path.write_bytes(b"exit /b 1"); s.scan()
    info.path.unlink(); s.scan(); s.scan()
    missing, changed = services.tamper.recent()
    assert changed == {"at": changed["at"], "event": "script_file_changed", "mcp_id": m.id, "kind": "start",
                       "path": str(info.path), "expected_sha256": info.sha256,
                       "actual_sha256": hashlib.sha256(b"exit /b 1").hexdigest()}
    assert missing == {"at": missing["at"], "event": "script_file_missing", "mcp_id": m.id, "kind": "start",
                       "path": str(info.path)}
    tamper_lines = await audit_events(services, "tamper")
    assert [e["event"] for e in tamper_lines] == ["script_file_changed", "script_file_missing"]

async def test_log_files_truncated_or_removed(services):
    d = services.paths.logs_dir
    for name in ("2026-11-01.jsonl", "2026-11-02.jsonl", "2026-11-03.jsonl.gz"):
        (d / name).write_bytes(b"x" * 100)
    s = scanner(services, {"cmd": None, "ps": None}); s.scan()
    (d / "2026-11-01.jsonl").write_bytes(b"x" * 10)
    (d / "2026-11-02.jsonl").unlink()
    s.expect_log_removed("2026-11-03.jsonl.gz"); (d / "2026-11-03.jsonl.gz").unlink()
    s.scan()
    recs = sorted((r["event"], r["file"]) for r in services.tamper.recent())
    assert recs == [("log_file_removed", "2026-11-02.jsonl"), ("log_file_truncated", "2026-11-01.jsonl")]

async def test_log_scan_ignores_growth_other_names_and_reports_each_change_once(services):
    d = services.paths.logs_dir
    (d / "2026-11-01.jsonl").write_bytes(b"x" * 100)
    (d / "notes.txt").write_bytes(b"x" * 100)
    s = scanner(services, {"cmd": None, "ps": None}); s.scan()
    (d / "2026-11-01.jsonl").write_bytes(b"x" * 200)  # growth (today's file) is normal
    (d / "notes.txt").unlink()
    s.scan(); assert services.tamper.recent() == []
    (d / "2026-11-01.jsonl").write_bytes(b"x" * 50); s.scan(); s.scan()
    [rec] = services.tamper.recent()
    assert (rec["event"], rec["file"], rec["before"], rec["after"]) == ("log_file_truncated", "2026-11-01.jsonl", 200, 50)
    # an announced removal that never happens stays announced until the file goes
    s.expect_log_removed("2026-11-01.jsonl"); s.scan()
    (d / "2026-11-01.jsonl").unlink(); s.scan()
    assert len(services.tamper.recent()) == 1


async def test_a_cancelled_log_removal_is_reported_again(services):
    d = services.paths.logs_dir
    (d / "2026-11-01.jsonl").write_bytes(b"x")
    s = scanner(services, {"cmd": None, "ps": None}); s.scan()
    s.expect_log_removed("2026-11-01.jsonl"); s.cancel_log_removal("2026-11-01.jsonl")
    s.cancel_log_removal("2026-11-02.jsonl")  # never announced: no error
    (d / "2026-11-01.jsonl").unlink(); s.scan()
    assert [(r["event"], r["file"]) for r in services.tamper.recent()] == [("log_file_removed", "2026-11-01.jsonl")]

async def test_scan_every_scans_at_once_then_every_interval_and_logs_failures(services):
    calls = []

    class Scanner:
        def scan(self):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("boom")

    task = asyncio.create_task(scan_every(Scanner(), services.collectors, interval_sec=0.01))
    try:
        await eventually(lambda: len(calls) >= 3)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    failed = [e for e in await audit_events(services, "system") if e.get("event") == "collector.handler_failed"]
    assert [(e["source"], e["error"]) for e in failed] == [("tamper-scan", "RuntimeError('boom')")]

async def test_first_scan_runs_without_waiting_for_the_interval(services):
    calls = []

    class Scanner:
        def scan(self):
            calls.append(1)

    task = asyncio.create_task(scan_every(Scanner(), services.collectors, interval_sec=60))
    try:
        await eventually(lambda: calls == [1])
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

def test_services_always_have_a_scanner(services):
    assert isinstance(services.tamper_scanner, TamperScanner)

async def _audit_configs(svc):
    await svc.log.flush()
    if not (svc.paths.logs_dir / "2026-11-04.jsonl").exists():
        return []
    return [e for e in await audit_events(svc, "system") if e.get("event") == "audit.config"]

@pytest.mark.parametrize("wts", [False, True])
async def test_build_services_runs_the_scan_task_only_with_collection(tmp_path, clock, wts):
    from app.collect.config import CollectorConfig
    from app.services import build_services
    from tests.fakes import CapturingOtpProvider, FakeProber, FakeRunner
    from tests.session_helpers import snap
    from tests.winfakes import FakeWtsSource
    cfg = CollectorConfig(wts=FakeWtsSource([snap(clock.now())]) if wts else None)
    svc = build_services(tmp_path, clock=clock, otp_provider=CapturingOtpProvider(), runner=FakeRunner(),
                         prober=FakeProber(clock), collectors=cfg)
    await svc.log.start()
    try:
        await svc.collectors.start()
        try:
            if wts:
                assert any(t.get_name() == "tamper-scan" for t in asyncio.all_tasks())
                for _ in range(200):  # the first scan (registry baseline) runs as soon as the task does
                    if await _audit_configs(svc):
                        break
                    await asyncio.sleep(0.01)
            else:
                await asyncio.sleep(0.05)
                assert not any(t.get_name() == "tamper-scan" for t in asyncio.all_tasks())
        finally:
            await svc.collectors.stop()
        assert len(await _audit_configs(svc)) == (1 if wts else 0)
    finally:
        await svc.log.stop()
        svc.db.close()

async def test_build_services_reports_cleared_logs_and_policy_changes_from_the_event_log(tmp_path, clock):
    from app.collect.config import CollectorConfig
    from app.services import build_services
    from tests.fakes import CapturingOtpProvider, FakeProber, FakeRunner
    src = FakeEventLogSource()
    src.queue("Security", [evt_xml("Security", 4719, 31, "2026-11-04T04:58:00Z", data={
        **SUBJ, "CategoryId": "%%8274", "SubcategoryGuid": "{0CCE922B-69AE-11D9-BED3-505054503030}", "AuditPolicyChanges": "%%8448"})])
    src.queue("System", [evt_xml("System", 104, 32, "2026-11-04T04:59:00Z", provider="Microsoft-Windows-Eventlog",
                                 user_data=("LogFileCleared", {**SUBJ, "Channel": "Application"}))])
    svc = build_services(tmp_path, clock=clock, otp_provider=CapturingOtpProvider(), runner=FakeRunner(),
                         prober=FakeProber(clock), collectors=CollectorConfig(event_log=src, activity=False))
    await svc.log.start()
    try:
        await svc.collectors.start()
        try:
            await eventually(lambda: len(svc.tamper.recent()) == 2)
        finally:
            await svc.collectors.stop()
        assert sorted((r["event"], r["source"], r["record_id"]) for r in svc.tamper.recent()) == [
            ("audit_policy_changed", "eventlog:4719", 31), ("log_cleared", "eventlog:104", 32)]
    finally:
        await svc.log.stop()
        svc.db.close()

# ---- Plan 5 Task 7 (preflight F07): the baselines survive a service restart ----

def persisted(services, values, path):
    return TamperScanner(services.tamper, services.scripts, services.mcps, services.paths.logs_dir, services.log,
                         read_value=lambda v: values[v.name], registry=(RegistryValue("A", "cmd"), RegistryValue("B", "ps")),
                         baseline_path=path)

async def test_changes_made_while_stopped_are_reported_at_the_next_start(services, tmp_path):
    d = services.paths.logs_dir; path = tmp_path / "data" / "tamper-baseline.json"
    for name in ("2026-11-01.jsonl", "2026-11-02.jsonl", "2026-11-03.jsonl"):
        (d / name).write_bytes(b"x" * 100)
    m = seed_mcp(services, make_user(services, "o@x.com")); info = services.scripts.get(m.id, "start")
    values = {"cmd": 1, "ps": None}
    persisted(services, values, path).scan()
    assert path.exists() and services.tamper.recent() == []
    # --- the service is stopped; someone edits things; the service starts again ---
    values["cmd"] = 0
    (d / "2026-11-01.jsonl").write_bytes(b"x" * 10)
    (d / "2026-11-02.jsonl").unlink()
    (d / "2026-11-03.jsonl").write_bytes(b"x" * 300)  # growth stays normal
    info.path.write_bytes(b"exit /b 9")
    s = persisted(services, values, path); s.scan(); s.scan()
    got = sorted((r["event"], r.get("key") or r.get("file") or r.get("kind")) for r in services.tamper.recent())
    assert got == [("audit_config_changed", "A\\cmd"), ("log_file_removed", "2026-11-02.jsonl"),
                   ("log_file_truncated", "2026-11-01.jsonl"), ("script_file_changed", "start")]
    by_event = {r["event"]: r for r in services.tamper.recent()}
    assert (by_event["audit_config_changed"]["before"], by_event["audit_config_changed"]["after"]) == (1, 0)
    assert (by_event["log_file_truncated"]["before"], by_event["log_file_truncated"]["after"]) == (100, 10)
    assert by_event["audit_config_changed"]["while_stopped"] is True and by_event["log_file_removed"]["while_stopped"] is True
    # every start still logs the registry values it found
    assert [e["values"] for e in await audit_events(services, "system") if e.get("event") == "audit.config"] == [
        {"A\\cmd": 1, "B\\ps": None}, {"A\\cmd": 0, "B\\ps": None}]

async def test_an_unfixed_script_change_is_not_reported_again_after_a_restart(services, tmp_path):
    path = tmp_path / "data" / "tamper-baseline.json"
    m = seed_mcp(services, make_user(services, "o@x.com")); info = services.scripts.get(m.id, "start")
    original = info.path.read_bytes()
    s = persisted(services, {"cmd": None, "ps": None}, path); s.scan()
    info.path.write_bytes(b"exit /b 1"); s.scan()
    persisted(services, {"cmd": None, "ps": None}, path).scan()
    assert [r["event"] for r in services.tamper.recent()] == ["script_file_changed"]
    info.path.write_bytes(original); persisted(services, {"cmd": None, "ps": None}, path).scan()
    info.path.write_bytes(b"exit /b 1"); persisted(services, {"cmd": None, "ps": None}, path).scan()
    assert [r["event"] for r in services.tamper.recent()] == ["script_file_changed", "script_file_changed"]

async def test_announced_removals_survive_a_restart_even_without_a_scan(services, tmp_path):
    d = services.paths.logs_dir; path = tmp_path / "data" / "tamper-baseline.json"
    for name in ("2026-11-01.jsonl", "2026-11-02.jsonl", "2026-11-03.jsonl"):
        (d / name).write_bytes(b"x")
    s = persisted(services, {"cmd": None, "ps": None}, path); s.scan()
    s.expect_log_removed("2026-11-01.jsonl"); (d / "2026-11-01.jsonl").unlink()  # retention, then a stop
    quiet = persisted(services, {"cmd": None, "ps": None}, path)  # a run without scanning (no collection)
    quiet.expect_log_removed("2026-11-02.jsonl"); (d / "2026-11-02.jsonl").unlink()
    quiet.expect_log_removed("2026-11-03.jsonl"); quiet.cancel_log_removal("2026-11-03.jsonl")
    (d / "2026-11-03.jsonl").unlink()
    persisted(services, {"cmd": None, "ps": None}, path).scan()
    assert [(r["event"], r["file"]) for r in services.tamper.recent()] == [("log_file_removed", "2026-11-03.jsonl")]

async def test_a_corrupt_or_missing_baseline_starts_fresh(services, tmp_path, capsys):
    d = services.paths.logs_dir; path = tmp_path / "data" / "tamper-baseline.json"
    (d / "2026-11-01.jsonl").write_bytes(b"x" * 100)
    persisted(services, {"cmd": 1, "ps": None}, path).scan()  # no file yet: a first run, nothing reported
    for junk in ("{not json", "[1, 2]", '{"version": 1, "registry": [1], "logs": {}}'):
        path.write_text(junk, "utf-8")
        persisted(services, {"cmd": 0, "ps": None}, path).scan()
        assert "tamper-baseline: corrupt file, starting fresh" in capsys.readouterr().err
    assert services.tamper.recent() == []
    assert json.loads(path.read_text("utf-8"))["registry"] == {"A\\cmd": 0, "B\\ps": None}  # rewritten

async def test_a_failing_save_is_logged_once_and_never_breaks_the_scan(services, tmp_path):
    path = tmp_path / "data" / "tamper-baseline.json"
    path.mkdir(parents=True)  # a directory where the file should go: every save fails
    s = persisted(services, {"cmd": 1, "ps": None}, path)
    s.scan(); s.scan(); s.expect_log_removed("2026-11-01.jsonl")
    failed = [e for e in await audit_events(services, "system") if e.get("event") == "tamper.baseline_save_failed"]
    assert len(failed) == 1 and failed[0]["path"] == str(path)

async def test_services_keep_the_baseline_in_the_data_dir(services):
    (services.paths.logs_dir / "2026-11-01.jsonl").write_bytes(b"x" * 7)
    services.tamper_scanner.scan()
    saved = json.loads((services.paths.data_dir / "tamper-baseline.json").read_text("utf-8"))
    assert saved["logs"]["2026-11-01.jsonl"] == 7 and set(saved["registry"]) == {v.key for v in AUDIT_REGISTRY}

@pytest.mark.winlive
def test_read_hklm_on_this_pc_returns_values_or_none():
    assert read_hklm(RegistryValue(r"SOFTWARE\mcp-monitor-test-missing-key", "Nope")) is None
    assert read_hklm(RegistryValue(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "CurrentBuild")) not in (None, "")
    assert all(v is None or isinstance(v, int | str) for v in (read_hklm(r) for r in AUDIT_REGISTRY))
