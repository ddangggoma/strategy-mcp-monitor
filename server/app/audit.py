from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Literal

from app.logstore.writer import LogWriter
from app.users.store import User
from app.web.channels import Channel


_THROTTLE_WINDOW_SEC = 600
_THROTTLE_PURGE_AT = 1024
_THROTTLE_MAX = 10000


class AuditLogger:
    """Thin typed facade over LogWriter for the `auth` and `admin.audit` categories."""

    def __init__(self, log: LogWriter) -> None:
        self._log = log
        # (event, ip) -> time of the last audited rate-limit hit; insertion-ordered, bounded
        self._throttle: dict[tuple[str, str], datetime] = {}

    @property
    def throttle_size(self) -> int:
        return len(self._throttle)

    def auth_rate_limited(
        self,
        event: str,
        email: str,
        channel: Channel,
        ip: str | None,
        user_agent: str | None,
        now: datetime,
    ) -> None:
        """Audit a rate-limited (429) auth attempt, but only the first per (event, ip) per window.

        Keeps a client that is already being rejected from flooding the log.
        """
        window = timedelta(seconds=_THROTTLE_WINDOW_SEC)
        key = (event, ip or "unknown")
        last = self._throttle.get(key)
        if last is not None and now - last < window:
            return
        self._throttle.pop(key, None)
        if len(self._throttle) >= _THROTTLE_PURGE_AT:
            self._throttle = {k: t for k, t in self._throttle.items() if now - t < window}
        while len(self._throttle) >= _THROTTLE_MAX:  # still full: evict the oldest entries
            del self._throttle[next(iter(self._throttle))]
        self._throttle[key] = now
        self.auth(
            event=event, email=email, channel=channel, ip=ip, user_agent=user_agent, ok=False
        )

    def auth(
        self,
        event: str,
        email: str,
        channel: Channel,
        ip: str | None,
        user_agent: str | None,
        ok: bool,
    ) -> None:
        self._log.emit(
            "auth", event=event, email=email, channel=channel, ip=ip, user_agent=user_agent, ok=ok
        )

    def admin(
        self,
        actor: User | None,
        action: str,
        channel: Channel,
        ip: str | None,
        target: Mapping,
        result: Literal["ok", "denied", "error"],
    ) -> None:
        self._log.emit(
            "admin.audit",
            actor_id=actor.id if actor else None,
            actor_email=actor.email if actor else None,
            action=action,
            channel=channel,
            ip=ip,
            target=dict(target),
            result=result,
        )
