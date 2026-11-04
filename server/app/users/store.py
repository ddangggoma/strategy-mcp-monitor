from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, get_args

from app.clock import Clock
from app.db import Database

Role = Literal["developer", "admin"]
_ROLES = get_args(Role)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InvalidEmailError(ValueError):
    pass


class UserExistsError(Exception):
    pass


class LastAdminError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


class BootstrapDoneError(Exception):
    """The first admin already exists (users table is not empty)."""


MAX_EMAIL_LENGTH = 320


def normalize_email(raw: str) -> str:
    email = raw.strip().lower()
    if len(email) > MAX_EMAIL_LENGTH or not _EMAIL_RE.match(email):
        raise InvalidEmailError(raw)
    try:
        email.encode("utf-8")  # lone surrogates cannot be stored or hashed
    except UnicodeEncodeError:
        raise InvalidEmailError(raw) from None
    return email


def _clean_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")
    return name


def _check_role(role: str) -> None:
    if role not in _ROLES:
        raise ValueError(f"invalid role: {role!r}")


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str
    role: Role
    active: bool
    created_at: datetime
    created_by: int | None
    last_login_at: datetime | None


def _to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        role=row["role"],
        active=bool(row["active"]),
        created_at=_parse_dt(row["created_at"]),
        created_by=row["created_by"],
        last_login_at=_parse_dt(row["last_login_at"]),
    )


class UserStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def create(
        self, email: str, name: str, role: Role, created_by: int | None
    ) -> User:
        email = normalize_email(email)
        name = _clean_name(name)
        _check_role(role)
        try:
            user_id = self._db.execute(
                "INSERT INTO users (email, name, role, active, created_at, created_by)"
                " VALUES (?, ?, ?, 1, ?, ?)",
                (email, name, role, self._clock.now().isoformat(), created_by),
            )
        except sqlite3.IntegrityError as exc:
            raise UserExistsError(email) from exc
        return self._require(user_id)

    def create_first_admin(self, email: str, name: str) -> User:
        """Create the initial admin iff no user exists; count and insert share one transaction.

        Raises InvalidEmailError / ValueError for bad input, BootstrapDoneError if any user exists.
        """
        email = normalize_email(email)
        name = _clean_name(name)
        with self._db.transaction() as conn:
            if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
                raise BootstrapDoneError()
            user_id = conn.execute(
                "INSERT INTO users (email, name, role, active, created_at, created_by)"
                " VALUES (?, ?, 'admin', 1, ?, NULL)",
                (email, name, self._clock.now().isoformat()),
            ).lastrowid
        return self._require(user_id)

    def get(self, user_id: int) -> User | None:
        rows = self._db.query("SELECT * FROM users WHERE id = ?", (user_id,))
        return _to_user(rows[0]) if rows else None

    def get_by_email(self, email: str) -> User | None:
        try:
            email = normalize_email(email)
        except InvalidEmailError:
            return None
        rows = self._db.query("SELECT * FROM users WHERE email = ?", (email,))
        return _to_user(rows[0]) if rows else None

    def list(self) -> list[User]:
        return [_to_user(r) for r in self._db.query("SELECT * FROM users ORDER BY id")]

    def count(self) -> int:
        return self._db.query("SELECT COUNT(*) AS n FROM users")[0]["n"]

    def set_role(self, user_id: int, role: Role) -> User:
        _check_role(role)
        self._update_guarded(user_id, role=role, active=None)
        return self._require(user_id)

    def set_active(self, user_id: int, active: bool) -> User:
        self._update_guarded(user_id, role=None, active=active)
        return self._require(user_id)

    def set_name(self, user_id: int, name: str) -> User:
        name = _clean_name(name)
        self._db.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
        return self._require(user_id)

    def touch_login(self, user_id: int) -> None:
        self._db.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (self._clock.now().isoformat(), user_id),
        )

    def _require(self, user_id: int) -> User:
        user = self.get(user_id)
        if user is None:
            raise UserNotFoundError(user_id)
        return user

    def _update_guarded(
        self, user_id: int, role: str | None, active: bool | None
    ) -> None:
        """Apply a role/active change, refusing to remove the last active admin.

        Count and update run in one BEGIN IMMEDIATE transaction on the same
        connection, so concurrent demotions cannot both succeed.
        """
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT role, active FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if row is None:
                raise UserNotFoundError(user_id)
            new_role = role if role is not None else row["role"]
            new_active = int(active) if active is not None else row["active"]
            was_active_admin = row["role"] == "admin" and row["active"] == 1
            stays_active_admin = new_role == "admin" and new_active == 1
            if was_active_admin and not stays_active_admin:
                n = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1"
                ).fetchone()[0]
                if n <= 1:
                    raise LastAdminError(user_id)
            conn.execute(
                "UPDATE users SET role = ?, active = ? WHERE id = ?",
                (new_role, new_active, user_id),
            )
