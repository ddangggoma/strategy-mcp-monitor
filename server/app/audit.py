from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from app.logstore.writer import LogWriter
from app.users.store import User
from app.web.channels import Channel


class AuditLogger:
    """Thin typed facade over LogWriter for the `auth` and `admin.audit` categories."""

    def __init__(self, log: LogWriter) -> None:
        self._log = log

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
