import asyncio
from pathlib import Path

import pytest

from app.activity.agent_supervisor import AgentOptions, AgentSupervisor
from app.collect.config import CollectorConfig
from app.services import build_services
from app.win.launch import LaunchError
from app.win.peer import PeerInfo
from tests.fakes import CapturingOtpProvider, FakeProber, FakeRunner
from tests.session_helpers import T0, snap, ws
from tests.test_auth_api import audit_events
from tests.winfakes import FakeLauncher, eventually


@pytest.fixture
def sup(services, clock, tmp_path):
    launcher = FakeLauncher()
    s = AgentSupervisor(services.agents, launcher, services.rdp, services.tamper, services.log, clock,
                        AgentOptions(dialog="print", url_dir=tmp_path, python="py.exe", agent_dir=Path("C:/agent"), stop_grace_sec=0.01))
    s.configure("http://127.0.0.1:8700"); services.rdp.add_listener(s.on_session_change)
    return s, launcher, tmp_path

def events(services, limit=50):
    return [r["event"] for r in services.tamper.recent(limit)]

async def test_opened_session_launches_agent_with_token_env_and_args(services, clock, sup):
    s, launcher, tmp = sup; services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    [spec] = launcher.specs
    assert spec.session_id == 2 and spec.cwd == Path("C:/agent")
    assert spec.argv == ["py.exe", "-m", "mcp_agent", "--server", "http://127.0.0.1:8700", "--dialog", "print", "--url-file", str(tmp / "agent-2.url")]
    assert spec.env["PYTHONPATH"] == str(Path("C:/agent"))
    assert services.agents.authenticate(spec.env["MCPMON_AGENT_TOKEN"], PeerInfo(1, 2, None, None)).session_id == 2
    assert [e["event"] for e in await audit_events(services, "system") if e.get("event", "").startswith("agent.")] == ["agent.launched"]

async def test_agent_exit_logs_tamper_and_relaunches_with_backoff(services, clock, sup):
    s, launcher, _ = sup; services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    launcher.procs[0].exit(1); await s.tick()
    clock.advance(2); await s.tick(); assert events(services) == []
    clock.advance(1.5); await s.tick()
    rec = services.tamper.recent(1)[0]
    assert (rec["event"], rec["session_id"], rec["exit_code"]) == ("agent_exited", 2, 1) and len(launcher.specs) == 1
    clock.advance(1); await s.tick(); assert len(launcher.specs) == 2
    launcher.procs[1].exit(1); await s.tick(); clock.advance(3.5); await s.tick()
    clock.advance(1); await s.tick(); assert len(launcher.specs) == 2
    clock.advance(1); await s.tick(); assert len(launcher.specs) == 3
    un = [e for e in await audit_events(services, "notice") if e["event"] == "notice_unacknowledged"]
    assert [e["reason"] for e in un] == ["agent_exited", "agent_exited"]

async def test_exit_after_logoff_is_not_tamper(services, clock, sup):
    s, launcher, _ = sup; services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    launcher.procs[0].exit(0); await s.tick()
    services.rdp.apply(snap(clock.now()))  # logoff
    clock.advance(5); await s.tick(); clock.advance(60); await s.tick()
    assert events(services) == [] and len(launcher.specs) == 1

async def test_hello_timeout_kills_once_and_reports_unresponsive(services, clock, sup):
    s, launcher, _ = sup; services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    clock.advance(31); await s.tick()
    assert launcher.procs[0].killed and events(services) == ["agent_unresponsive"]
    assert services.tamper.recent(1)[0]["stage"] == "hello"
    await s.tick(); clock.advance(3.5); await s.tick()
    assert events(services) == ["agent_unresponsive"]

async def test_restart_storm_reported_once_per_window(services, clock, sup):
    s, launcher, _ = sup; services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    for i in range(7):
        launcher.procs[i].exit(1); await s.tick(); clock.advance(3.5); await s.tick(); clock.advance(31); await s.tick()
    assert events(services).count("agent_restart_storm") == 1 and events(services).count("agent_exited") == 7

async def test_pending_notice_reshown_after_restart(services, clock, sup):
    s, launcher, _ = sup; services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    d = services.displays.pending_for_session(2)
    launcher.procs[0].exit(1); await s.tick(); clock.advance(3.5); await s.tick(); clock.advance(1); await s.tick()
    token = launcher.specs[1].env["MCPMON_AGENT_TOKEN"]
    slot = services.agents.authenticate(token, PeerInfo(1001, 2, None, None))
    services.agents.hello(slot, session_id=2, pid=1001, version="0.1.0", peer=PeerInfo(1001, 2, None, None))
    cmd = await services.agents.next(slot, 0)
    assert (cmd["type"], cmd["display_id"], cmd["attempt"]) == ("show_notice", d.id, 1)

async def test_launch_failure_is_logged_and_retried(services, clock, sup):
    """Plan test with a transient error: ruling F22 stops retries of a deterministic
    ``session_mismatch`` (see test_session_mismatch_is_logged_once_and_retried_on_the_next_open)."""
    s, launcher, _ = sup; launcher.fail_next = LaunchError("OSError(5, 'Access is denied')")
    services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    fails = [e for e in await audit_events(services, "system") if e.get("event") == "agent.launch_failed"]
    assert fails[0]["error"] == "OSError(5, 'Access is denied')" and launcher.specs == []
    assert (fails[0]["session_id"], fails[0]["launcher"]) == (2, "fake")
    clock.advance(1); await s.tick(); assert len(launcher.specs) == 1

async def test_stop_asks_agents_to_exit_then_kills(services, clock, sup):
    s, launcher, _ = sup; services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    slot = services.agents.slot(2)
    await s.stop()
    assert list(slot.commands)[-1] == {"type": "exit"} and launcher.procs[0].killed


# --- beyond the plan's tests ---------------------------------------------------------------

def hello(services, launcher, i, *, pid=None):
    """The i-th launched agent says hello from ``pid`` (default: the launcher's pid)."""
    pid = launcher.procs[i].pid if pid is None else pid
    peer = PeerInfo(pid, launcher.specs[i].session_id, None, None)
    slot = services.agents.authenticate(launcher.specs[i].env["MCPMON_AGENT_TOKEN"], peer)
    services.agents.hello(slot, session_id=peer.session_id, pid=pid, version="0.1.0", peer=peer)
    return slot

async def test_agent_exited_reports_launcher_pid_agent_pid_user_and_restarts(services, clock, sup):
    """F08: ``pid`` is what the launcher started, ``agent_pid`` the pid the agent said hello from."""
    s, launcher, _ = sup; services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    launcher.procs[0].exit(1); await s.tick(); clock.advance(3.5); await s.tick(); clock.advance(1); await s.tick()
    hello(services, launcher, 1, pid=5555)
    launcher.procs[1].exit(3); await s.tick(); clock.advance(3.5); await s.tick()
    first, second = reversed([r for r in services.tamper.recent() if r["event"] == "agent_exited"])
    assert (first["pid"], first["agent_pid"], first["restarts"], first["user"]) == (1000, None, 0, "CORP\\hong")
    assert (second["pid"], second["agent_pid"], second["exit_code"], second["restarts"]) == (1001, 5555, 3, 1)
    launched = [e for e in await audit_events(services, "system") if e.get("event") == "agent.launched"]
    assert [(e["session_id"], e["pid"], e["launcher"]) for e in launched] == [(2, 1000, "fake"), (2, 1001, "fake")]

async def test_launch_uses_account_token_and_edge_dialog_has_no_url_file(services, clock):
    launcher = FakeLauncher()
    s = AgentSupervisor(services.agents, launcher, services.rdp, services.tamper, services.log, clock,
                        AgentOptions(python="py.exe", agent_dir=Path("C:/agent")))
    services.rdp.add_listener(s.on_session_change)
    services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    [spec] = launcher.specs
    assert spec.argv == ["py.exe", "-m", "mcp_agent", "--server", "http://127.0.0.1:8700", "--dialog", "edge"]
    assert set(spec.env) == {"MCPMON_AGENT_TOKEN", "MCPMON_AGENT_SERVER_KEY", "PYTHONPATH"}
    assert spec.env["MCPMON_AGENT_SERVER_KEY"] == services.agents.slot(2).server_key
    assert len(bytes.fromhex(spec.env["MCPMON_AGENT_SERVER_KEY"])) == 32
    assert services.agents.slot(2).user == "CORP\\hong"

def test_print_dialog_needs_a_url_dir(services, clock):
    with pytest.raises(ValueError, match="url_dir"):
        AgentSupervisor(services.agents, FakeLauncher(), services.rdp, services.tamper, services.log, clock,
                        AgentOptions(dialog="print"))

async def test_print_dialog_creates_the_url_dir(services, clock, tmp_path):
    launcher = FakeLauncher(); run = tmp_path / "run" / "deeper"
    s = AgentSupervisor(services.agents, launcher, services.rdp, services.tamper, services.log, clock,
                        AgentOptions(dialog="print", url_dir=run))
    services.rdp.add_listener(s.on_session_change)
    services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    assert run.is_dir() and launcher.specs[0].argv[-1] == str(run / "agent-2.url")

async def test_heartbeat_timeout_after_hello(services, clock, sup):
    s, launcher, _ = sup; services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    slot = hello(services, launcher, 0, pid=4242)
    for _ in range(3):  # heartbeats keep it alive well past the hello timeout
        clock.advance(15); services.agents.heartbeat(slot, idle_sec=None, locked=None); await s.tick()
    assert events(services) == [] and not launcher.procs[0].killed
    clock.advance(21); await s.tick()
    rec = services.tamper.recent(1)[0]
    assert (rec["event"], rec["stage"], rec["pid"], rec["agent_pid"], rec["user"]) == ("agent_unresponsive", "heartbeat", 1000, 4242, "CORP\\hong")
    assert launcher.procs[0].killed
    clock.advance(30); await s.tick()
    assert events(services) == ["agent_unresponsive"]

async def test_killed_agent_is_not_agent_exited_but_relaunched(services, clock, sup):
    s, launcher, _ = sup; services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    clock.advance(31); await s.tick(); await s.tick(); clock.advance(3.5); await s.tick()
    assert "agent_exited" not in events(services) and len(launcher.specs) == 1
    clock.advance(1); await s.tick()
    assert len(launcher.specs) == 2 and services.agents.slot(2) is not None

async def test_healthy_agent_resets_the_backoff(services, clock, sup):
    s, launcher, _ = sup; services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    launcher.procs[0].exit(1); await s.tick(); clock.advance(3.5); await s.tick(); clock.advance(1); await s.tick()  # 1 failure
    slot = hello(services, launcher, 1)
    for _ in range(4):  # alive and heartbeating for 76 s > healthy_reset_sec
        clock.advance(19); services.agents.heartbeat(slot, idle_sec=None, locked=None); await s.tick()
    launcher.procs[1].exit(1); await s.tick(); clock.advance(3.5); await s.tick()
    clock.advance(1); await s.tick()
    assert len(launcher.specs) == 3  # backoff[0] again, not backoff[1]

async def test_backoff_caps_at_the_last_step(services, clock, tmp_path):
    launcher = FakeLauncher()
    s = AgentSupervisor(services.agents, launcher, services.rdp, services.tamper, services.log, clock,
                        AgentOptions(backoff=(1, 5)))
    services.rdp.add_listener(s.on_session_change)
    services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    for i, wait in enumerate((1, 5, 5)):
        launcher.procs[i].exit(1); await s.tick(); clock.advance(3.5); await s.tick()
        clock.advance(wait - 0.5); await s.tick(); assert len(launcher.specs) == i + 1
        clock.advance(0.5); await s.tick(); assert len(launcher.specs) == i + 2

async def test_session_mismatch_is_logged_once_and_retried_on_the_next_open(services, clock, sup):
    """F22: a deterministic ``session_mismatch`` is not retried on the backoff, only on the next ``Opened``."""
    s, launcher, _ = sup; launcher.fail_next = LaunchError("session_mismatch")
    services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    for _ in range(5):
        clock.advance(31); await s.tick()
    fails = [e for e in await audit_events(services, "system") if e.get("event") == "agent.launch_failed"]
    assert [f["error"] for f in fails] == ["session_mismatch"] and launcher.specs == []
    assert services.agents.slot(2) is None  # the token minted for the failed launch was revoked
    services.rdp.apply(snap(clock.now(), ws(2, state="disconnected")))
    services.rdp.apply(snap(clock.now(), ws(2, connected=clock.now()))); await s.tick()  # reconnect → Opened
    assert len(launcher.specs) == 1

async def test_logoff_closes_with_forget_kills_and_logs_agent_stopped(services, clock, sup):
    s, launcher, _ = sup; services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    slot = hello(services, launcher, 0, pid=4242)
    services.rdp.apply(snap(clock.now())); await s.tick()  # logoff of a connected session → Closed(logoff)
    assert launcher.procs[0].killed and services.agents.slot(2) is None and slot.wake.is_set()
    clock.advance(10); await s.tick()
    stopped = [e for e in await audit_events(services, "session") if e["event"] == "agent_stopped"]
    assert [(e["session_id"], e["reason"], e["pid"], e["agent_pid"], e["user"]) for e in stopped] == [(2, "logoff", 1000, 4242, "CORP\\hong")]
    assert events(services) == [] and len(launcher.specs) == 1

async def test_exit_then_logoff_of_a_disconnected_session_logs_agent_stopped_after_grace(services, clock, sup):
    """No ``Closed(logoff)`` for a disconnected session: the tick sees the context gone after the grace."""
    s, launcher, _ = sup; services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    services.rdp.apply(snap(clock.now(), ws(2, state="disconnected")))
    launcher.procs[0].exit(0); await s.tick()
    services.rdp.apply(snap(clock.now()))  # logoff while disconnected
    assert not launcher.procs[0].killed
    clock.advance(3.5); await s.tick(); clock.advance(60); await s.tick()
    stopped = [e for e in await audit_events(services, "session") if e["event"] == "agent_stopped"]
    assert [(e["session_id"], e["reason"]) for e in stopped] == [(2, "logoff")]
    assert events(services) == [] and len(launcher.specs) == 1 and services.agents.slot(2) is None

async def test_pending_relaunch_is_dropped_when_the_session_is_gone(services, clock, sup):
    s, launcher, _ = sup; launcher.fail_next = LaunchError("transient")
    services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    services.rdp.apply(snap(clock.now(), ws(2, state="disconnected")))
    services.rdp.apply(snap(clock.now()))  # logoff while disconnected: no Closed(logoff)
    clock.advance(2); await s.tick(); clock.advance(30); await s.tick()
    assert launcher.specs == []

async def test_disconnect_keeps_the_agent_and_reconnect_shows_one_notice(services, clock, sup):
    """F09 through the supervisor: a reconnect with a live, hello'd agent queues one show_notice, attempt 1."""
    s, launcher, _ = sup; services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    slot = hello(services, launcher, 0)
    assert (await services.agents.next(slot, 0))["attempt"] == 1
    services.rdp.apply(snap(clock.now(), ws(2, state="disconnected")))
    clock.advance(30)
    services.rdp.apply(snap(clock.now(), ws(2, connected=clock.now())))
    assert len(launcher.specs) == 1 and not launcher.procs[0].killed
    d = services.displays.pending_for_session(2)
    [cmd] = [c for c in slot.commands if c["type"] == "show_notice"]
    assert (cmd["display_id"], cmd["attempt"], d.attempts) == (d.id, 1, 1)

async def test_two_sessions_are_supervised_independently(services, clock, sup):
    s, launcher, _ = sup
    services.rdp.apply(snap(clock.now(), ws(2), ws(3, user="kim", ip="10.0.3.22", name="KIM-PC"))); await s.tick()
    assert [sp.session_id for sp in launcher.specs] == [2, 3]
    launcher.procs[1].exit(1); await s.tick(); clock.advance(3.5); await s.tick()
    [rec] = [r for r in services.tamper.recent() if r["event"] == "agent_exited"]
    assert (rec["session_id"], rec["user"]) == (3, "CORP\\kim") and not launcher.procs[0].killed
    clock.advance(1); await s.tick()
    assert [sp.session_id for sp in launcher.specs] == [2, 3, 3]

async def test_stop_lets_agents_that_exit_go_without_kill_and_ends_supervision(services, clock):
    launcher = FakeLauncher()
    s = AgentSupervisor(services.agents, launcher, services.rdp, services.tamper, services.log, clock,
                        AgentOptions(stop_grace_sec=5))
    services.rdp.add_listener(s.on_session_change)
    services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    loop = asyncio.get_running_loop(); started = loop.time()
    loop.call_later(0.02, launcher.procs[0].exit, 0)  # the agent obeys the exit command
    await s.stop()
    assert not launcher.procs[0].killed and loop.time() - started < 2
    assert services.agents.slot(2) is None
    clock.advance(60); await s.tick()
    services.rdp.apply(snap(clock.now(), ws(2, state="disconnected")))
    services.rdp.apply(snap(clock.now(), ws(2, connected=clock.now())))
    assert len(launcher.specs) == 1 and events(services) == []


# --- wiring through build_services / Collectors (F07) -----------------------------------------

@pytest.fixture
async def wired(tmp_path, clock):
    launcher = FakeLauncher()
    svc = build_services(tmp_path, clock=clock, otp_provider=CapturingOtpProvider(), runner=FakeRunner(),
                         prober=FakeProber(clock),
                         collectors=CollectorConfig(launcher=launcher, agent=AgentOptions(tick_sec=0.01, stop_grace_sec=0.01)))
    await svc.log.start()
    try:
        yield svc, launcher
    finally:
        await svc.collectors.stop()
        await svc.log.stop()
        svc.db.close()

def test_no_launcher_no_supervisor(services):
    assert services.agent_supervisor is None

async def test_build_services_registers_the_supervisor_after_the_display_listener(wired, clock):
    svc, launcher = wired
    assert svc.agent_supervisor is not None
    svc.agent_supervisor.configure("http://127.0.0.1:9999")
    svc.rdp.apply(snap(clock.now(), ws(2, logon=T0))); await svc.agent_supervisor.tick()
    [spec] = launcher.specs
    assert spec.argv[spec.argv.index("--server") + 1] == "http://127.0.0.1:9999"
    assert svc.displays.pending_for_session(2) is not None  # the display existed before the launch

async def test_collectors_run_the_tick_loop_and_stop_the_agents_first(wired, clock):
    svc, launcher = wired
    await svc.collectors.start()
    launcher.fail_next = LaunchError("transient")
    svc.rdp.apply(snap(clock.now(), ws(2)))
    await eventually(lambda: launcher.fail_next is None and svc.agents.slot(2) is None)  # run() woke; the launch failed
    assert launcher.specs == []
    clock.advance(1)
    await eventually(lambda: len(launcher.specs) == 1)  # relaunched by run(), not by a test tick
    slot = svc.agents.slot(2)
    await svc.collectors.stop()
    assert list(slot.commands)[-1] == {"type": "exit"} and launcher.procs[0].killed
    assert svc.agents.slot(2) is None


# --- M5: a killed agent's process handle is closed even after its session is forgotten -----------

from types import SimpleNamespace  # noqa: E402

from app.win.launch import HandleProcess  # noqa: E402


class _HandleLauncher:
    """Hands out real ``HandleProcess``es over a fake WTS API: TerminateProcess takes effect on the
    next exit-code query (like the real one, which returns before the process is gone)."""
    name = "wts"

    def __init__(self):
        self.state, self.closed = {}, []
        self.api = SimpleNamespace(
            get_exit_code=lambda h: self.state[h], close_handle=self.closed.append,
            terminate=lambda h: self.state.__setitem__(h, "dying"))
        self._next = 0

    def launch(self, spec):
        self._next += 1
        h = f"h{self._next}"
        self.state[h] = 259
        return HandleProcess(h, 100 + self._next, self._query(h))

    def _query(self, h):
        api = self.api
        def get_exit_code(handle):
            if self.state[handle] == "dying":
                self.state[handle] = 1
                return 259  # still running right after TerminateProcess
            return self.state[handle]
        return SimpleNamespace(get_exit_code=get_exit_code, close_handle=api.close_handle, terminate=api.terminate)


async def test_forget_reaps_the_killed_process_so_its_handle_is_closed(services, clock, tmp_path):
    launcher = _HandleLauncher()
    s = AgentSupervisor(services.agents, launcher, services.rdp, services.tamper, services.log, clock,
                        AgentOptions(dialog="print", url_dir=tmp_path, python="py.exe", agent_dir=Path("C:/agent")))
    services.rdp.add_listener(s.on_session_change)
    services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    services.rdp.apply(snap(clock.now()))  # logoff → forget → TerminateProcess
    assert launcher.closed == []  # not gone yet
    await s.tick()
    assert launcher.closed == []  # still exiting
    await s.tick()
    assert launcher.closed == ["h1"]
    await s.tick()
    assert launcher.closed == ["h1"]  # closed once


async def test_stop_reaps_the_processes_it_killed(services, clock, tmp_path):
    launcher = _HandleLauncher()
    s = AgentSupervisor(services.agents, launcher, services.rdp, services.tamper, services.log, clock,
                        AgentOptions(dialog="print", url_dir=tmp_path, python="py.exe", agent_dir=Path("C:/agent"),
                                     stop_grace_sec=0.01))
    services.rdp.add_listener(s.on_session_change)
    services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    await s.stop()
    assert launcher.closed == ["h1"]


# --- M14: process creation and kills run off the event loop -----------------------------------

import threading  # noqa: E402


class _BlockingLauncher(FakeLauncher):
    """``launch`` blocks the calling thread until ``release`` is set (``entered`` says it started)."""

    def __init__(self):
        super().__init__()
        self.entered, self.release = threading.Event(), threading.Event()

    def launch(self, spec):
        self.entered.set()
        assert self.release.wait(5), "launch was never released"
        return super().launch(spec)


def blocking_sup(services, clock, tmp_path, **opts):
    launcher = _BlockingLauncher()
    s = AgentSupervisor(services.agents, launcher, services.rdp, services.tamper, services.log, clock,
                        AgentOptions(dialog="print", url_dir=tmp_path, python="py.exe", agent_dir=Path("C:/agent"),
                                     stop_grace_sec=0.01, **opts))
    services.rdp.add_listener(s.on_session_change)
    return s, launcher

async def test_launches_and_kills_run_in_worker_threads(services, clock, sup):
    s, launcher, _ = sup; loop_thread = threading.get_ident()
    services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    clock.advance(31); await s.tick(); await s.tick()  # no hello: killed as unresponsive; its exit seen
    clock.advance(3.5); await s.tick(); clock.advance(1); await s.tick()  # relaunched
    services.rdp.apply(snap(clock.now()))  # logoff → forget: the kill waits for the tick
    assert not launcher.procs[1].killed
    await s.tick()
    assert launcher.procs[1].killed and len(launcher.threads) == 2
    assert loop_thread not in launcher.threads
    assert loop_thread not in launcher.procs[0].kill_threads + launcher.procs[1].kill_threads

async def test_the_loop_keeps_running_while_a_launch_blocks(services, clock, tmp_path):
    s, launcher = blocking_sup(services, clock, tmp_path)
    services.rdp.apply(snap(clock.now(), ws(2)))
    tick = asyncio.create_task(s.tick())
    await eventually(launcher.entered.is_set)
    loop = asyncio.get_running_loop(); started = loop.time()
    await asyncio.sleep(0.01)
    assert loop.time() - started < 1 and not tick.done() and launcher.specs == []
    launcher.release.set(); await tick
    assert len(launcher.specs) == 1 and services.agents.slot(2) is not None

async def test_logoff_during_a_launch_kills_what_it_started(services, clock, tmp_path):
    s, launcher = blocking_sup(services, clock, tmp_path)
    services.rdp.apply(snap(clock.now(), ws(2)))
    tick = asyncio.create_task(s.tick())
    await eventually(launcher.entered.is_set)
    services.rdp.apply(snap(clock.now()))  # logoff while the process is being created
    launcher.release.set(); await tick
    assert launcher.procs[0].killed and services.agents.slot(2) is None
    clock.advance(60); await s.tick()
    assert len(launcher.specs) == 1 and events(services) == []
    services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()  # the next logon gets a new agent
    assert len(launcher.specs) == 2 and not launcher.procs[1].killed and services.agents.slot(2) is not None

async def test_an_open_during_a_launch_does_not_launch_twice(services, clock, tmp_path):
    s, launcher = blocking_sup(services, clock, tmp_path)
    services.rdp.apply(snap(clock.now(), ws(2)))
    tick = asyncio.create_task(s.tick())
    await eventually(launcher.entered.is_set)
    services.rdp.apply(snap(clock.now(), ws(2, state="disconnected")))
    services.rdp.apply(snap(clock.now(), ws(2, connected=clock.now())))  # Opened while launching
    launcher.release.set(); await tick
    await s.tick(); clock.advance(5); await s.tick()
    assert len(launcher.specs) == 1 and not launcher.procs[0].killed

async def test_stop_waits_for_a_launch_in_flight_and_kills_it(services, clock, tmp_path):
    s, launcher = blocking_sup(services, clock, tmp_path)
    services.rdp.apply(snap(clock.now(), ws(2)))
    tick = asyncio.create_task(s.tick())
    await eventually(launcher.entered.is_set)
    stop = asyncio.create_task(s.stop())
    await asyncio.sleep(0.05)
    assert not stop.done()  # waits for the tick's launch
    launcher.release.set(); await stop; await tick
    assert launcher.procs[0].killed and services.agents.slot(2) is None
    launched = [e for e in await audit_events(services, "system") if e.get("event") == "agent.launched"]
    assert [e["pid"] for e in launched] == [1000]

async def test_run_wakes_for_a_launch_and_a_logoff_kill(services, clock, tmp_path):
    launcher = FakeLauncher()
    s = AgentSupervisor(services.agents, launcher, services.rdp, services.tamper, services.log, clock,
                        AgentOptions(tick_sec=60, stop_grace_sec=0.01))
    services.rdp.add_listener(s.on_session_change)
    run = asyncio.create_task(s.run())
    try:
        await asyncio.sleep(0.01)  # the first tick ran; the next one is 60 s away
        services.rdp.apply(snap(clock.now(), ws(2)))
        await eventually(lambda: len(launcher.specs) == 1, timeout=2)
        services.rdp.apply(snap(clock.now()))  # logoff
        await eventually(lambda: launcher.procs[0].killed, timeout=2)
    finally:
        await s.stop(); run.cancel()
        await asyncio.gather(run, return_exceptions=True)

async def test_an_unexpected_launcher_error_is_a_launch_failure_and_retried(services, clock, sup):
    s, launcher, _ = sup; launcher.fail_next = RuntimeError("boom")
    services.rdp.apply(snap(clock.now(), ws(2))); await s.tick()
    fails = [e for e in await audit_events(services, "system") if e.get("event") == "agent.launch_failed"]
    assert [f["error"] for f in fails] == ["RuntimeError('boom')"] and services.agents.slot(2) is None
    clock.advance(1); await s.tick()
    assert len(launcher.specs) == 1
