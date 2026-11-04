from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.audit import cap_user_agent
from app.clock import Clock
from app.db import Database
from app.web.channels import Channel

SESSION_ABSOLUTE_SEC = 28800
SESSION_IDLE_SEC = 1800


@dataclass(frozen=True)
class AuthSession:
    user_id: int
    channel: Channel
    csrf_token: str = field(repr=False)
    created_at: datetime
    last_seen_at: datetime


def _hash_id(session_id: str) -> str | None:
    """sha256 hex of the id; None if it cannot be UTF-8 encoded (lone surrogates)."""
    try:
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        return None


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class SessionStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def create(
        self, user_id: int, channel: Channel, ip: str | None, user_agent: str | None
    ) -> tuple[str, str]:
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(24)
        now = self._clock.now().astimezone(timezone.utc).isoformat()
        self._db.execute(
            "INSERT INTO auth_sessions"
            " (id_hash, user_id, channel, csrf_token, created_at, last_seen_at, ip, user_agent)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (_hash_id(session_id), user_id, channel, csrf_token, now, now, ip, cap_user_agent(user_agent)),
        )
        return session_id, csrf_token

    def get(self, session_id: str, channel: Channel) -> AuthSession | None:
        """Return the live session for this channel, sliding last_seen_at; else None.

        Never raises on attacker-controlled ids. A session presented on the wrong
        channel is rejected without being touched or deleted. Expired rows are
        deleted when found. Read, expiry check and touch share one transaction.
        """
        id_hash = _hash_id(session_id)
        if id_hash is None:
            return None
        now = self._clock.now().astimezone(timezone.utc)
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT user_id, channel, csrf_token, created_at, last_seen_at"
                " FROM auth_sessions WHERE id_hash = ?",
                (id_hash,),
            ).fetchone()
            if row is None or row["channel"] != channel:
                return None
            created_at = _parse_dt(row["created_at"])
            last_seen_at = _parse_dt(row["last_seen_at"])
            if (
                (now - created_at).total_seconds() >= SESSION_ABSOLUTE_SEC
                or (now - last_seen_at).total_seconds() >= SESSION_IDLE_SEC
            ):
                conn.execute("DELETE FROM auth_sessions WHERE id_hash = ?", (id_hash,))
                return None
            conn.execute(
                "UPDATE auth_sessions SET last_seen_at = ? WHERE id_hash = ?",
                (now.isoformat(), id_hash),
            )
            return AuthSession(
                user_id=row["user_id"],
                channel=row["channel"],
                csrf_token=row["csrf_token"],
                created_at=created_at,
                last_seen_at=now,
            )

    def revoke(self, session_id: str) -> None:
        id_hash = _hash_id(session_id)
        if id_hash is None:
            return
        self._db.execute("DELETE FROM auth_sessions WHERE id_hash = ?", (id_hash,))

    def revoke_user(self, user_id: int) -> None:
        self._db.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
