from __future__ import annotations

import hmac
import math
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from app.clock import Clock, to_kst_iso
from app.db import Database
from app.users.store import InvalidEmailError, User, UserStore, normalize_email

OTP_TTL_SEC = 300
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SEC = 60
OTP_IP_LIMIT = 10
OTP_IP_WINDOW_SEC = 600
OTP_VERIFY_IP_LIMIT = 30
OTP_VERIFY_IP_WINDOW_SEC = 600
OTP_EMAIL_FAIL_LIMIT = 10
OTP_EMAIL_FAIL_WINDOW_SEC = 3600


class OtpProvider(Protocol):
    def send(self, email: str, code: str) -> None: ...


class DummyOtpProvider:
    """Dev provider: appends '<KST ts> <email> <code>' to an outbox file and echoes it."""

    def __init__(self, outbox: Path, echo: Callable[[str], None] = print) -> None:
        self._outbox = outbox
        self._echo = echo

    def send(self, email: str, code: str) -> None:
        line = f"{to_kst_iso(datetime.now(UTC))} {email} {code}"
        self._outbox.parent.mkdir(parents=True, exist_ok=True)
        with self._outbox.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        self._echo(line)


class OtpRateLimitError(Exception):
    def __init__(self, retry_after: int, scope: Literal["ip", "email"] = "ip") -> None:
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after
        self.scope = scope


def _parse(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _retry_after(until: datetime, now: datetime) -> int:
    return max(1, math.ceil((until - now).total_seconds()))


class OtpService:
    def __init__(
        self,
        db: Database,
        users: UserStore,
        provider: OtpProvider,
        clock: Clock,
        secret: bytes,
        dev_fixed_code: str | None = None,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("OTP secret must be at least 32 bytes")
        self._db = db
        self._users = users
        self.provider = provider
        self._clock = clock
        self._secret = secret
        self._dev_fixed_code = dev_fixed_code

    def _hash(self, email: str, code: str) -> str:
        return hmac.new(self._secret, f"{email}:{code}".encode(), "sha256").hexdigest()

    def _lockout_retry_after(self, conn, email: str, now: datetime) -> int | None:
        """Prune old failures; return seconds until the email unlocks, or None."""
        window = timedelta(seconds=OTP_EMAIL_FAIL_WINDOW_SEC)
        conn.execute(
            "DELETE FROM otp_failures WHERE at <= ?", (to_kst_iso(now - window),)
        )
        rows = conn.execute(
            "SELECT at FROM otp_failures WHERE email = ?", (email,)
        ).fetchall()
        if len(rows) < OTP_EMAIL_FAIL_LIMIT:
            return None
        times = sorted(_parse(r["at"]) for r in rows)
        # Unlocks once enough old failures expire to drop below the limit.
        pivot = times[len(times) - OTP_EMAIL_FAIL_LIMIT]
        return _retry_after(pivot + window, now)

    def request(self, email: str, ip: str) -> None:
        """Issue a code.

        Raises InvalidEmailError for malformed input and OtpRateLimitError when
        the IP limit or per-email cooldown applies. Unknown/inactive emails
        behave identically (row with NULL hash, same cooldown) but send nothing.
        """
        email = normalize_email(email)
        now = self._clock.now()
        now_iso = to_kst_iso(now)
        window_start = now - timedelta(seconds=OTP_IP_WINDOW_SEC)

        code: str | None = None
        code_hash: str | None = None
        expires_at: str | None = None
        user = self._users.get_by_email(email)
        if user is not None and user.active:
            code = f"{secrets.randbelow(10**6):06d}"
            code_hash = self._hash(email, code)
            expires_at = to_kst_iso(now + timedelta(seconds=OTP_TTL_SEC))

        with self._db.transaction() as conn:
            conn.execute(
                "DELETE FROM otp_ip_requests WHERE at <= ?", (to_kst_iso(window_start),)
            )
            ip_rows = conn.execute(
                "SELECT at FROM otp_ip_requests WHERE ip = ?", (ip,)
            ).fetchall()
            if len(ip_rows) >= OTP_IP_LIMIT:
                oldest = min(_parse(r["at"]) for r in ip_rows)
                raise OtpRateLimitError(
                    _retry_after(oldest + timedelta(seconds=OTP_IP_WINDOW_SEC), now), "ip"
                )
            locked = self._lockout_retry_after(conn, email, now)
            if locked is not None:
                raise OtpRateLimitError(locked, "email")
            row = conn.execute(
                "SELECT last_sent_at FROM otp_codes WHERE email = ?", (email,)
            ).fetchone()
            if row is not None:
                ready = _parse(row["last_sent_at"]) + timedelta(
                    seconds=OTP_RESEND_COOLDOWN_SEC
                )
                if ready > now:
                    raise OtpRateLimitError(_retry_after(ready, now), "email")
            conn.execute(
                "INSERT INTO otp_ip_requests (ip, at) VALUES (?, ?)", (ip, now_iso)
            )
            conn.execute(
                "INSERT INTO otp_codes (email, code_hash, expires_at, attempts, last_sent_at)"
                " VALUES (?, ?, ?, 0, ?)"
                " ON CONFLICT(email) DO UPDATE SET code_hash = excluded.code_hash,"
                " expires_at = excluded.expires_at, attempts = 0,"
                " last_sent_at = excluded.last_sent_at",
                (email, code_hash, expires_at, now_iso),
            )
        if code is not None:
            self.provider.send(email, code)

    def _consume_verify_ip_budget(self, ip: str, now: datetime) -> None:
        """Record this verify attempt for the IP, or raise OtpRateLimitError if it is over budget."""
        window = timedelta(seconds=OTP_VERIFY_IP_WINDOW_SEC)
        with self._db.transaction() as conn:
            conn.execute(
                "DELETE FROM otp_verify_ip WHERE at <= ?", (to_kst_iso(now - window),)
            )
            rows = conn.execute(
                "SELECT at FROM otp_verify_ip WHERE ip = ?", (ip,)
            ).fetchall()
            if len(rows) >= OTP_VERIFY_IP_LIMIT:
                oldest = min(_parse(r["at"]) for r in rows)
                raise OtpRateLimitError(_retry_after(oldest + window, now), "ip")
            conn.execute(
                "INSERT INTO otp_verify_ip (ip, at) VALUES (?, ?)", (ip, to_kst_iso(now))
            )

    def verify(self, email: str, code: str, ip: str) -> User | None:
        """Return the user on success (the code is consumed), else None.

        Raises OtpRateLimitError, before any other work, when `ip` has used up its
        verify budget; every other call (success or failure) counts against it.
        Every call against an existing row counts as an attempt, malformed
        codes included; after OTP_MAX_ATTEMPTS the code is invalidated.
        """
        now = self._clock.now()
        self._consume_verify_ip_budget(ip, now)
        try:
            email = normalize_email(email)
        except InvalidEmailError:
            return None
        if not code.isascii():
            code = ""  # can never match; still counts as an attempt (and avoids encode errors)

        with self._db.transaction() as conn:
            if self._lockout_retry_after(conn, email, now) is not None:
                return None
            # Re-check the user inside the transaction that consumes the code.
            user = self._users.get_by_email(email)
            active_user = user if user is not None and user.active else None
            row = conn.execute(
                "SELECT code_hash, expires_at, attempts FROM otp_codes WHERE email = ?",
                (email,),
            ).fetchone()
            if row is None:
                # No code was ever requested; only the dev fixed code can pass.
                return active_user if self._fixed_code_ok(code, active_user) else None

            ok = False
            attempts = row["attempts"]
            if attempts < OTP_MAX_ATTEMPTS:
                attempts += 1
                stored = row["code_hash"]
                hash_ok = stored is not None and hmac.compare_digest(
                    self._hash(email, code), stored
                )
                fresh = row["expires_at"] is not None and now < _parse(
                    row["expires_at"]
                )
                ok = active_user is not None and (
                    (hash_ok and fresh) or self._fixed_code_ok(code, active_user)
                )
            if ok:
                conn.execute(
                    "UPDATE otp_codes SET code_hash = NULL, expires_at = NULL,"
                    " attempts = ? WHERE email = ?",
                    (attempts, email),
                )
                return active_user
            conn.execute(
                "UPDATE otp_codes SET attempts = ?,"
                " code_hash = CASE WHEN ? THEN NULL ELSE code_hash END WHERE email = ?",
                (attempts, attempts >= OTP_MAX_ATTEMPTS, email),
            )
            conn.execute(
                "INSERT INTO otp_failures (email, at) VALUES (?, ?)",
                (email, to_kst_iso(now)),
            )
            return None

    def _fixed_code_ok(self, code: str, user: User | None) -> bool:
        if self._dev_fixed_code is None or user is None:
            return False
        return hmac.compare_digest(code.encode(), self._dev_fixed_code.encode())
