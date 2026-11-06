from __future__ import annotations

import functools
import secrets
from dataclasses import dataclass
from pathlib import Path

from app.activity.agent_hub import AgentHub
from app.activity.agent_supervisor import AgentSupervisor
from app.activity.context import ActivityContext
from app.activity.powershell import PowerShellHandler, expire_every
from app.activity.process import CommandHandler, ProcessActivityHandler, ProcessComponent
from app.activity.tamper import TamperEventHandler, TamperMonitor, TamperScanner, scan_every
from app.audit import AuditLogger
from app.auth.otp import DummyOtpProvider, OtpProvider, OtpService
from app.auth.sessions import SessionStore
from app.clock import Clock, SystemClock
from app.collect.config import CollectorConfig
from app.collect.eventlog import BookmarkStore, EventLogComponent
from app.collect.manager import Collectors, SessionsComponent
from app.db import Database
from app.logstore.indexer import LogIndex
from app.logstore.retention import RetentionJob
from app.logstore.writer import DailyJsonlWriter, LogWriter
from app.monitor.bus import BoardBus
from app.monitor.history import McpHistory
from app.monitor.probes import Prober
from app.monitor.runner import ScriptRunner
from app.monitor.scripts import ScriptStore
from app.monitor.store import McpStore
from app.monitor.supervisor import Monitor, ProberLike, ScriptRunnerLike
from app.notice.displays import NoticeDisplays
from app.notice.store import NoticeStore
from app.paths import AppPaths
from app.sessions.eventmap import SessionEventHandler
from app.sessions.history import SessionHistory
from app.sessions.rdns import ReverseDns
from app.sessions.tracker import SessionTracker
from app.settings.store import SettingsStore
from app.users.store import UserStore
from app.win.peer import PeerResolver, PsutilPeerResolver

_OTP_SECRET_NAME = "otp_secret"


@dataclass
class Services:
    paths: AppPaths
    db: Database
    clock: Clock
    settings: SettingsStore
    users: UserStore
    otp: OtpService
    sessions: SessionStore
    log: LogWriter
    audit: AuditLogger
    mcps: McpStore
    scripts: ScriptStore
    history: McpHistory
    bus: BoardBus
    tamper: TamperMonitor
    monitor: Monitor
    notice: NoticeStore
    peers: PeerResolver
    config_collectors: CollectorConfig
    rdp_history: SessionHistory
    rdp: SessionTracker
    """The RDP session tracker (``sessions`` is the login ``SessionStore``; ruling F01)."""
    displays: NoticeDisplays
    """Notice displays per RDP connection; its tracker listener runs before every other one."""
    collectors: Collectors
    """Windows collectors; ``serve()`` starts them after the monitor and stops them before it."""
    eventlog: EventLogComponent | None
    """Event log subscriptions when ``CollectorConfig.event_log`` is set; mappers register their
    handlers with ``eventlog.on(...)`` inside ``build_services`` (before ``collectors.start()``)."""
    activity_context: ActivityContext
    """Process → session resolution and the session fields of every ``activity.*`` line."""
    agents: AgentHub
    """Per-session agent slots behind ``/api/agent/*`` (Local only); a display listener."""
    agent_supervisor: AgentSupervisor | None
    """Launches and watches the session agents when ``CollectorConfig.launcher`` is set."""
    tamper_scanner: TamperScanner
    """Audit registry / script file / log file checks; scanned every 60 s by the ``tamper-scan``
    collector task when collection is on (``CollectorConfig.wts``)."""
    log_index: LogIndex
    """The log search index ``data/index.db``; woken by every log flush. ``serve()`` starts it
    after the log writer and stops it before."""
    retention: RetentionJob
    """The daily log retention job (W14); ``serve()`` starts it after the log index and stops it
    first. Fixtures do not start it (tests call ``run_once``)."""


def _load_or_create_otp_secret(db: Database) -> bytes:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT value FROM secrets WHERE name = ?", (_OTP_SECRET_NAME,)
        ).fetchone()
        if row is not None:
            return bytes.fromhex(row["value"])
        secret = secrets.token_bytes(32)
        conn.execute(
            "INSERT INTO secrets (name, value) VALUES (?, ?)", (_OTP_SECRET_NAME, secret.hex())
        )
        return secret


def build_services(
    root: Path,
    clock: Clock | None = None,
    otp_provider: OtpProvider | None = None,
    dev_fixed_code: str | None = None,
    runner: ScriptRunnerLike | None = None,
    prober: ProberLike | None = None,
    peer_resolver: PeerResolver | None = None,
    collectors: CollectorConfig | None = None,
) -> Services:
    """Wire all backend services. Starts neither the log writer nor the monitor (serve() / fixtures do)."""
    paths = AppPaths(Path(root))
    paths.ensure()
    db = Database(paths.db_path)
    db.migrate()
    clock = clock or SystemClock()
    users = UserStore(db, clock)
    provider = otp_provider or DummyOtpProvider(paths.dev_dir / "otp-outbox.log")
    otp = OtpService(
        db, users, provider, clock, _load_or_create_otp_secret(db), dev_fixed_code=dev_fixed_code
    )
    log = LogWriter(DailyJsonlWriter(paths.logs_dir), clock)
    log_index = LogIndex(paths.index_db_path, paths.logs_dir, clock, log)
    log.add_flush_listener(log_index.wake)
    settings = SettingsStore(db)
    mcps = McpStore(db, clock, users)
    scripts = ScriptStore(db, paths, clock, mcps)
    history = McpHistory(db, clock)
    bus = BoardBus()
    tamper = TamperMonitor(log, bus, clock)
    monitor = Monitor(
        mcps=mcps,
        scripts=scripts,
        history=history,
        settings=settings,
        runner=runner if runner is not None else ScriptRunner(),
        prober=prober if prober is not None else Prober(clock),
        log=log,
        bus=bus,
        clock=clock,
        tamper=tamper,
    )
    config_collectors = collectors or CollectorConfig()
    rdp_history = SessionHistory(db, clock)
    rdp = SessionTracker(
        rdp_history, clock, log, bus, collect_console=config_collectors.collect_console
    )
    notice = NoticeStore(db, clock)
    displays = NoticeDisplays(db, clock, log, notice, rdp, tamper)
    rdp.add_listener(displays.on_session_change)  # first: later listeners see the new display
    manager = Collectors(log, clock)
    activity_context = ActivityContext(rdp, clock)
    agents = AgentHub(
        clock, log, tamper, rdp, displays, activity_context,
        window_events=config_collectors.activity,
    )
    displays.add_listener(agents.on_display)
    agent_supervisor: AgentSupervisor | None = None
    if config_collectors.launcher is not None:
        agent_supervisor = AgentSupervisor(
            agents, config_collectors.launcher, rdp, tamper, log, clock, config_collectors.agent
        )
        rdp.add_listener(agent_supervisor.on_session_change)  # after displays: the display exists
        manager.add_task("agent-supervisor", agent_supervisor.run, stop=agent_supervisor.stop)
    tamper_scanner = TamperScanner(
        tamper, scripts, mcps, paths.logs_dir, log, baseline_path=paths.data_dir / "tamper-baseline.json"
    )
    audit = AuditLogger(log)
    retention = RetentionJob(paths, db, settings, log_index, log, audit, clock, tamper_scanner)
    if config_collectors.wts is not None:
        manager.add_task("tamper-scan", functools.partial(scan_every, tamper_scanner, manager))
        manager.add(SessionsComponent(
            config_collectors.wts, rdp, manager, ReverseDns(clock=clock), clock,
            interval_sec=config_collectors.poll_interval_sec, displays=displays,
        ))
    else:
        async def close_previous_displays() -> None:
            """M12: with no session source, a previous run's open displays still close."""
            try:
                displays.start()
            except Exception as exc:
                manager.handler_failed("notice-displays", exc)

        manager.add_task("notice-displays", close_previous_displays)
    eventlog: EventLogComponent | None = None
    if config_collectors.event_log is not None:
        bookmarks = BookmarkStore(
            config_collectors.bookmarks_path or paths.data_dir / "collector-state.json"
        )
        eventlog = EventLogComponent(config_collectors.event_log, bookmarks, manager, clock)
        session_events = SessionEventHandler(rdp_history, log)
        for channel in ("eventlog:security", "eventlog:lsm", "eventlog:rcm"):
            eventlog.on(channel, session_events)
        tamper_events = TamperEventHandler(tamper)
        for channel in ("eventlog:security", "eventlog:system"):
            eventlog.on(channel, tamper_events)
        if config_collectors.activity:
            eventlog.on("eventlog:security", CommandHandler(activity_context, log))
            script_blocks = PowerShellHandler(activity_context, log, clock)
            for channel in ("eventlog:powershell", "eventlog:pwsh"):
                eventlog.on(channel, script_blocks)
            manager.add_task(
                "powershell-expire", functools.partial(expire_every, script_blocks, manager)
            )
        manager.add(eventlog)
    if config_collectors.process is not None:
        manager.add(ProcessComponent(
            config_collectors.process, ProcessActivityHandler(activity_context, log), manager
        ))
    return Services(
        paths=paths,
        db=db,
        clock=clock,
        settings=settings,
        users=users,
        otp=otp,
        sessions=SessionStore(db, clock),
        log=log,
        audit=audit,
        mcps=mcps,
        scripts=scripts,
        history=history,
        bus=bus,
        tamper=tamper,
        monitor=monitor,
        notice=notice,
        peers=peer_resolver if peer_resolver is not None else PsutilPeerResolver(),
        config_collectors=config_collectors,
        rdp_history=rdp_history,
        rdp=rdp,
        displays=displays,
        collectors=manager,
        eventlog=eventlog,
        activity_context=activity_context,
        agents=agents,
        agent_supervisor=agent_supervisor,
        tamper_scanner=tamper_scanner,
        log_index=log_index,
        retention=retention,
    )
