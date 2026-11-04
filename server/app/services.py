from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path

from app.audit import AuditLogger
from app.auth.otp import DummyOtpProvider, OtpProvider, OtpService
from app.auth.sessions import SessionStore
from app.clock import Clock, SystemClock
from app.db import Database
from app.logstore.writer import DailyJsonlWriter, LogWriter
from app.paths import AppPaths
from app.settings.store import SettingsStore
from app.users.store import UserStore

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
) -> Services:
    """Wire all backend services. Does not start the log writer (serve() / fixtures do)."""
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
    return Services(
        paths=paths,
        db=db,
        clock=clock,
        settings=SettingsStore(db),
        users=users,
        otp=otp,
        sessions=SessionStore(db, clock),
        log=log,
        audit=AuditLogger(log),
    )
