"""What ``build_services`` collects. Later tasks add fields (process, activity, agent)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.win.eventlog import EventLogSource
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
