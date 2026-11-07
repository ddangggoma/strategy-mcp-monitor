"""What ``build_services`` collects and whether it supervises session agents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.activity.agent_supervisor import AgentOptions
from app.win.eventlog import EventLogSource
from app.win.launch import AgentLauncher
from app.win.wmi import ProcessEventSource
from app.win.wts import WtsSource


@dataclass(frozen=True)
class CollectorConfig:
    wts: WtsSource | None = None
    """The WTS session source; ``None`` = no session collection."""
    collect_console: bool = False
    """Also track the console session (development PCs have no RDP sessions)."""
    poll_interval_sec: float = 0.5
    event_log: EventLogSource | None = None
    """The Windows event log; ``None`` = no event log subscriptions."""
    bookmarks_path: Path | None = None
    """Event log bookmarks; ``None`` = ``<data_dir>/collector-state.json`` (V12)."""
    process: ProcessEventSource | None = None
    """WMI process start/stop events; ``None`` = no ``activity.process`` collection."""
    activity: bool = True
    """``--activity off`` (DEV/E2E, V24): no process events, no 4688/4104 command handlers."""
    launcher: AgentLauncher | None = None
    """How session agents are started; ``None`` = no agent supervisor."""
    agent: AgentOptions = AgentOptions()
