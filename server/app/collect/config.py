"""What ``build_services`` collects. Later tasks add fields (event log, process, activity, agent)."""

from __future__ import annotations

from dataclasses import dataclass

from app.win.wts import WtsSource


@dataclass(frozen=True)
class CollectorConfig:
    wts: WtsSource | None = None
    """The WTS session source; ``None`` = no session collection."""
    collect_console: bool = False
    """Also track the console session (development PCs have no RDP sessions)."""
    poll_interval_sec: float = 0.5
