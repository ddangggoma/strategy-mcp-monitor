import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.activity.context import ActivityContext
from app.activity.powershell import PowerShellHandler, ScriptBlockAssembler, expire_every
from app.activity.process import CommandHandler, map_4688
from app.win.eventlog import parse_event_xml
from tests.eventlog_helpers import evt_xml
from tests.session_helpers import snap, ws
from tests.test_auth_api import audit_events
from tests.winfakes import FakeEventLogSource, ListLog, eventually

USER = {"SubjectUserSid": "S-1-5-21-1-2-3-1001", "SubjectUserName": "hong", "SubjectDomainName": "CORP"}

def r4688(child, parent, cmd, rid=1, sid=None, pid="0x2274", ppid="0x1a2c"):
    data = {**USER, "NewProcessId": pid, "NewProcessName": child, "ProcessId": ppid, "CommandLine": cmd, "ParentProcessName": parent}
    if sid:
        data["SubjectUserSid"] = sid
    return parse_event_xml(evt_xml("Security", 4688, rid, "2026-11-04T04:59:00Z", data=data))

@pytest.mark.parametrize("child,parent,cmd,expect", [
    (r"C:\Windows\System32\cmd.exe", r"C:\Windows\explorer.exe", "cmd.exe /c deploy.bat", ("cmd", None)),
    (r"C:\Windows\System32\PING.EXE", r"C:\Windows\System32\cmd.exe", "ping -n 1 10.0.0.1", (None, "cmd")),
    (r"C:\Program Files\PowerShell\7\pwsh.exe", r"C:\Windows\explorer.exe", "pwsh -NoLogo", ("pwsh", None)),
    (r"C:\Windows\System32\conhost.exe", r"C:\Windows\System32\cmd.exe", r"\??\C:\Windows\system32\conhost.exe 0xffffffff", None),
    (r"C:\Windows\System32\notepad.exe", r"C:\Windows\explorer.exe", "notepad.exe", None),
])
def test_map_4688_keeps_only_shell_related_processes(child, parent, cmd, expect):
    c = map_4688(r4688(child, parent, cmd))
    if expect is None:
        assert c is None
    else:
        assert (c.shell, c.parent_shell, c.cmdline, c.pid, c.ppid, c.user, c.domain) == (*expect, cmd, 0x2274, 0x1A2C, "hong", "CORP")

def test_map_4688_skips_system_and_keeps_empty_cmdline_as_none():
    assert map_4688(r4688(r"C:\Windows\System32\cmd.exe", r"C:\x\svc.exe", "cmd /c x", sid="S-1-5-18")) is None
    assert map_4688(r4688(r"C:\Windows\System32\cmd.exe", r"C:\Windows\explorer.exe", "")).cmdline is None

async def test_command_handler_enriches_with_session_and_event_time(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    ctx = ActivityContext(services.rdp, clock, pid_session=lambda pid: None)
    CommandHandler(ctx, services.log)([r4688(r"C:\Windows\System32\cmd.exe", r"C:\Windows\explorer.exe", "cmd.exe /c deploy.bat", rid=9)])
    [e] = await audit_events(services, "activity.command")
    assert (e["ts"], e["event"], e["shell"], e["cmdline"], e["session_id"], e["user"], e["client_ip"], e["source"], e["record_id"]) == \
        ("2026-11-04T13:59:00.000+09:00", "process_cmdline", "cmd", "cmd.exe /c deploy.bat", 2, "CORP\\hong", "10.0.3.21", "eventlog:4688", 9)

PS = "Microsoft-Windows-PowerShell/Operational"
NOW = datetime(2026, 11, 4, 5, 0, tzinfo=UTC)

def r4104(text, n=1, total=1, sbid="{aaaa}", rid=1, channel=PS, sid="S-1-5-21-1-2-3-1001"):
    return parse_event_xml(evt_xml(channel, 4104, rid, "2026-11-04T04:59:50Z", provider="Microsoft-Windows-PowerShell",
        data={"MessageNumber": str(n), "MessageTotal": str(total), "ScriptBlockText": text, "ScriptBlockId": sbid, "Path": ""},
        pid=6000, user_sid=sid))

def test_script_block_single_part_and_system_skip():
    a = ScriptBlockAssembler()
    [b] = a.add(r4104("Get-Process | Stop-Process -Name notepad"), NOW)
    assert (b.shell, b.text, b.parts, b.total, b.truncated, b.incomplete, b.pid, b.path) == \
        ("powershell", "Get-Process | Stop-Process -Name notepad", 1, 1, False, False, 6000, None)
    assert a.add(r4104("x", sid="S-1-5-18", sbid="{bbbb}"), NOW) == []

def test_script_block_multi_part_in_order():
    a = ScriptBlockAssembler()
    assert a.add(r4104("world", n=2, total=2, rid=2), NOW) == []
    [b] = a.add(r4104("hello ", n=1, total=2, rid=1), NOW)
    assert (b.text, b.parts, b.total) == ("hello world", 2, 2)

def test_script_block_incomplete_after_timeout_and_truncated():
    a = ScriptBlockAssembler(max_wait_sec=5, max_chars=4)
    assert a.add(r4104("abc", n=1, total=3), NOW) == [] and a.expire(NOW + timedelta(seconds=4)) == []
    [b] = a.expire(NOW + timedelta(seconds=5))
    assert (b.text, b.incomplete, b.parts, b.total) == ("abc", True, 1, 3)
    [t] = a.add(r4104("가나다라마바", sbid="{cccc}"), NOW)
    assert (t.text, t.truncated) == ("가나다라", True)

def test_pwsh_channel_shell_name():
    [b] = ScriptBlockAssembler().add(r4104("1+1", channel="PowerShellCore/Operational"), NOW)
    assert b.shell == "pwsh"

async def test_powershell_handler_logs_with_account_and_event_time(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    h = PowerShellHandler(ActivityContext(services.rdp, clock, pid_session=lambda pid: 2), services.log, clock,
                          sid_to_account=lambda sid: "CORP\\hong")
    h([r4104("Get-ChildItem", rid=31)]); h.tick()
    [e] = await audit_events(services, "activity.command")
    assert (e["ts"], e["event"], e["shell"], e["text"], e["session_id"], e["user"], e["source"], e["record_id"]) == \
        ("2026-11-04T13:59:50.000+09:00", "script_block", "powershell", "Get-ChildItem", 2, "CORP\\hong", "eventlog:4104", 31)


# --- beyond the plan's tests -----------------------------------------------------------------

def test_map_4688_ignores_other_events_and_unreadable_pids():
    other = parse_event_xml(evt_xml("Security", 4624, 1, data={**USER, "NewProcessId": "0x10"}))
    assert map_4688(other) is None
    ps = parse_event_xml(evt_xml(PS, 4688, 1, data={**USER, "NewProcessId": "0x10", "NewProcessName": r"C:\cmd.exe"}))
    assert map_4688(ps) is None
    assert map_4688(r4688(r"C:\Windows\System32\cmd.exe", r"C:\Windows\explorer.exe", "cmd", pid="zz")) is None
    assert map_4688(r4688(r"C:\Windows\System32\cmd.exe", r"C:\Windows\explorer.exe", "cmd", ppid="zz")).ppid is None
    for sid in ("S-1-5-19", "S-1-5-20"):
        assert map_4688(r4688(r"C:\Windows\System32\cmd.exe", r"C:\x\svc.exe", "cmd", sid=sid)) is None

def test_map_4688_full_record_and_missing_parent_name():
    c = map_4688(r4688(r"C:\Windows\System32\WindowsPowerShell\v1.0\PowerShell.EXE", r"C:\Windows\System32\cmd.exe",
                       "powershell -nop", rid=44))
    assert (c.at, c.exe, c.parent_exe, c.shell, c.parent_shell, c.record_id) == (
        datetime(2026, 11, 4, 4, 59, tzinfo=UTC), r"C:\Windows\System32\WindowsPowerShell\v1.0\PowerShell.EXE",
        r"C:\Windows\System32\cmd.exe", "powershell", "cmd", 44)
    data = {**USER, "NewProcessId": "0x10", "NewProcessName": r"C:\Windows\System32\cmd.exe", "ProcessId": "0x4",
            "CommandLine": "cmd", "SubjectDomainName": ""}
    c = map_4688(parse_event_xml(evt_xml("Security", 4688, 2, data=data)))
    assert (c.parent_exe, c.parent_shell, c.shell, c.domain) == (None, None, "cmd", None)

async def test_command_handler_line_keys_remember_and_filters(services, clock):
    services.rdp.apply(snap(clock.now(), ws(2)))
    live = {0x2274: 2}
    ctx = ActivityContext(services.rdp, clock, pid_session=live.get)
    other = parse_event_xml(evt_xml("Security", 4624, 3, data=USER))
    notepad = r4688(r"C:\Windows\System32\notepad.exe", r"C:\Windows\explorer.exe", "notepad", rid=4, pid="0x99")
    ping = r4688(r"C:\Windows\System32\PING.EXE", r"C:\Windows\System32\cmd.exe", "ping x", rid=5)
    CommandHandler(ctx, services.log)([other, notepad, ping])
    [e] = await audit_events(services, "activity.command")
    assert {k: v for k, v in e.items() if k not in ("ts", "cat")} == {
        "event": "process_cmdline", "shell": None, "parent_shell": "cmd", "pid": 0x2274, "ppid": 0x1A2C,
        "exe": r"C:\Windows\System32\PING.EXE", "parent_exe": r"C:\Windows\System32\cmd.exe", "cmdline": "ping x",
        "source": "eventlog:4688", "record_id": 5, "session_id": 2, "user": "CORP\\hong",
        "client_ip": "10.0.3.21", "client_name": "HONG-LAPTOP"}
    live.clear()  # the process is gone: only the remembered pid still answers
    assert ctx.session_of(0x2274) == 2 and ctx.session_of(0x99) is None

async def test_command_handler_untracked_session_uses_the_event_account():
    from tests.fakes import FakeClock
    clock = FakeClock(NOW)
    log = ListLog()

    class NoSessions:
        def by_user(self, user, domain): return None
        def context(self, session_id): return None

    ctx = ActivityContext(NoSessions(), clock, pid_session=lambda pid: 7)
    data = {**USER, "NewProcessId": "0x10", "NewProcessName": r"C:\Windows\System32\cmd.exe", "ProcessId": "0x4",
            "CommandLine": "cmd", "ParentProcessName": r"C:\Windows\explorer.exe", "SubjectDomainName": ""}
    CommandHandler(ctx, log)([parse_event_xml(evt_xml("Security", 4688, 2, data=data))])
    [(cat, at, f)] = log.events
    assert (cat, at, f["session_id"], f["user"], f["client_ip"]) == (
        "activity.command", datetime(2026, 11, 4, 5, 0, 0, 123456, tzinfo=UTC), 7, "hong", None)

def test_script_block_first_fragment_fields_duplicates_and_defaults():
    a = ScriptBlockAssembler()
    later = r4104("b", n=2, total=2, rid=8)
    assert a.add(later, NOW) == [] and a.add(later, NOW) == []  # a repeated fragment counts once
    [b] = a.add(r4104("a", n=1, total=2, rid=7), NOW + timedelta(seconds=1))
    assert (b.text, b.parts, b.record_id, b.at, b.script_block_id, b.user_sid) == (
        "ab", 2, 8, datetime(2026, 11, 4, 4, 59, 50, tzinfo=UTC), "{aaaa}", "S-1-5-21-1-2-3-1001")
    assert a.expire(NOW + timedelta(seconds=60)) == []
    bare = parse_event_xml(evt_xml(PS, 4104, 9, provider="Microsoft-Windows-PowerShell", pid=6000,
                                   data={"ScriptBlockText": "dir", "ScriptBlockId": "{dddd}", "Path": r"C:\s\a.ps1"}))
    [d] = a.add(bare, NOW)
    assert (d.text, d.parts, d.total, d.path, d.user_sid) == ("dir", 1, 1, r"C:\s\a.ps1", None)

def test_script_block_same_id_on_two_channels_is_two_blocks():
    a = ScriptBlockAssembler()
    assert a.add(r4104("x", n=1, total=2), NOW) == []
    assert a.add(r4104("y", n=1, total=2, channel="PowerShellCore/Operational"), NOW) == []
    blocks = a.expire(NOW + timedelta(seconds=5))
    assert sorted((b.shell, b.text) for b in blocks) == [("powershell", "x"), ("pwsh", "y")]
    assert a.expire(NOW + timedelta(seconds=10)) == []

def test_script_block_flush_returns_pending_as_incomplete():
    a = ScriptBlockAssembler()
    assert a.add(r4104("part", n=1, total=4), NOW) == []
    [b] = a.flush()
    assert (b.text, b.incomplete, b.parts, b.total) == ("part", True, 1, 4) and a.flush() == []

async def test_powershell_handler_tick_expires_and_user_without_sid():
    from tests.fakes import FakeClock
    clock = FakeClock(NOW)
    log = ListLog()

    class NoSessions:
        def by_user(self, user, domain): return None
        def context(self, session_id): return None

    asked = []
    h = PowerShellHandler(ActivityContext(NoSessions(), clock, pid_session=lambda pid: None), log, clock,
                          sid_to_account=lambda sid: asked.append(sid) or "X\\y")
    bare = parse_event_xml(evt_xml(PS, 4104, 3, "2026-11-04T04:59:58Z", provider="Microsoft-Windows-PowerShell", pid=6000,
                                   data={"MessageNumber": "1", "MessageTotal": "2", "ScriptBlockText": "a", "ScriptBlockId": "{e}"}))
    h([bare]); h.tick()
    assert log.events == []
    clock.advance(5); h.tick()
    [(cat, at, f)] = log.events
    assert (cat, at, asked) == ("activity.command", datetime(2026, 11, 4, 4, 59, 58, tzinfo=UTC), [])
    assert f == {"event": "script_block", "shell": "powershell", "text": "a", "script_block_id": "{e}", "path": None,
                 "parts": 1, "truncated": False, "incomplete": True, "pid": 6000, "source": "eventlog:4104",
                 "record_id": 3, "session_id": None, "user": None, "client_ip": None, "client_name": None}

async def test_expire_every_ticks_reports_errors_and_flushes_on_cancel(services, clock):
    h = PowerShellHandler(ActivityContext(services.rdp, clock, pid_session=lambda pid: None), services.log, clock,
                          sid_to_account=lambda sid: None)
    real_tick = h.tick
    calls = []

    def tick():
        calls.append(clock.now())
        if len(calls) == 1:
            raise RuntimeError("boom")
        real_tick()

    h.tick = tick
    h([r4104("one", n=1, total=2, sbid="{1}", rid=1)])
    task = asyncio.create_task(expire_every(h, services.collectors, interval_sec=0.01))
    try:
        await eventually(lambda: len(calls) >= 2)
        clock.advance(5)
        await eventually(lambda: len(calls) >= 4)
        h([r4104("two", n=1, total=2, sbid="{2}", rid=2)])
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    lines = await audit_events(services, "activity.command")
    assert [(e["text"], e["incomplete"]) for e in lines] == [("one", True), ("two", True)]
    failed = [e for e in await audit_events(services, "system") if e.get("event") == "collector.handler_failed"]
    assert [(e["source"], e["error"]) for e in failed] == [("powershell-expire", "RuntimeError('boom')")]


SEC, PSC = "Security", "PowerShellCore/Operational"

@pytest.mark.parametrize("activity", [True, False])
async def test_build_services_registers_command_handlers_only_with_activity(tmp_path, clock, activity):
    from app.collect.config import CollectorConfig
    from app.services import build_services
    from tests.fakes import CapturingOtpProvider, FakeProber, FakeRunner
    src = FakeEventLogSource()
    src.queue(SEC, [evt_xml(SEC, 4688, 21, "2026-11-04T04:59:00Z", data={
        **USER, "NewProcessId": "0x10", "NewProcessName": r"C:\Windows\System32\cmd.exe", "ProcessId": "0x4",
        "CommandLine": "cmd /c x", "ParentProcessName": r"C:\Windows\explorer.exe"})])
    src.queue(PS, [evt_xml(PS, 4104, 22, "2026-11-04T04:59:50Z", provider="Microsoft-Windows-PowerShell", pid=6000,
                           data={"MessageNumber": "1", "MessageTotal": "2", "ScriptBlockText": "half", "ScriptBlockId": "{f}"})])
    svc = build_services(tmp_path, clock=clock, otp_provider=CapturingOtpProvider(), runner=FakeRunner(),
                         prober=FakeProber(clock), collectors=CollectorConfig(event_log=src, activity=activity))
    await svc.log.start()
    try:
        await svc.collectors.start()
        try:
            await eventually(lambda: SEC in {o[0] for o in src.opened})
            if activity:
                await eventually(lambda: {o[0] for o in src.opened} == {SEC, PS, PSC, SYS, *_SESSION_CHANNELS})
                # the clock moves on until the 1 s expiry task completes the half block as incomplete
                lines = await _command_lines_until(svc, clock, lambda ls: len(ls) == 2)
                assert sorted((e["event"], e["record_id"]) for e in lines) == [("process_cmdline", 21), ("script_block", 22)]
                assert [e["incomplete"] for e in lines if e["event"] == "script_block"] == [True]
            else:
                await asyncio.sleep(0.2)
                assert {o[0] for o in src.opened} == {SEC, SYS, *_SESSION_CHANNELS}
        finally:
            await svc.collectors.stop()
        if not activity:
            assert await _command_lines_until(svc, clock, lambda ls: True) == []
    finally:
        await svc.log.stop()
        svc.db.close()

SYS = "System"  # the tamper handler (Task 14) listens there whether activity is on or off
_SESSION_CHANNELS = ("Microsoft-Windows-TerminalServices-LocalSessionManager/Operational",
                     "Microsoft-Windows-TerminalServices-RemoteConnectionManager/Operational")

async def _command_lines_until(svc, clock, pred, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        await svc.log.flush()
        path = svc.paths.logs_dir / "2026-11-04.jsonl"
        lines = [e for e in await audit_events(svc, "activity.command")] if path.exists() else []
        if pred(lines):
            return lines
        if loop.time() >= deadline:
            raise AssertionError(f"activity.command lines so far: {lines}")
        clock.advance(1)
        await asyncio.sleep(0.02)


async def test_a_4688_command_line_with_a_notice_token_is_redacted(services, clock):
    """I2: ``start msedge --app=<notice url>`` from cmd must not write the token to the log."""
    services.rdp.apply(snap(clock.now(), ws(2)))
    h = CommandHandler(ActivityContext(services.rdp, clock), services.log)
    h([r4688(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Windows\System32\cmd.exe",
             "msedge.exe --app=http://127.0.0.1:8700/notice#d=3&t=SECRETtoken123")])
    [line] = await audit_events(services, "activity.command")
    assert line["cmdline"] == "msedge.exe --app=http://127.0.0.1:8700/notice#d=3&t=<redacted>"
