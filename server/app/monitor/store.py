from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.clock import Clock
from app.db import Database
from app.monitor.models import Mcp, McpConfig
from app.users.store import UserStore


class McpNotFoundError(Exception):
    pass


class NameTakenError(Exception):
    pass


class EndpointTakenError(Exception):
    pass


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def validation_reason(exc: ValidationError) -> str:
    """A compact, input-free summary of a ValidationError (safe to log)."""
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'config'}: {e['msg']}"
        for e in exc.errors(include_url=False, include_input=False)
    )


def _unvalidated_config(row: sqlite3.Row) -> McpConfig:
    """The stored values without validation, for listing a row the validator now rejects."""
    try:
        raw = json.loads(row["config"])
    except (TypeError, ValueError):
        raw = None
    fields = McpConfig.model_fields
    values = {k: v for k, v in raw.items() if k in fields} if isinstance(raw, dict) else {}
    values = {"name": row["name"], "host": row["host"], "port": row["port"], **values}
    return McpConfig.model_construct(**values)


def _to_mcp(row: sqlite3.Row) -> Mcp:
    error: str | None = None
    try:
        config = McpConfig.model_validate_json(row["config"])
    except ValidationError as exc:
        error = validation_reason(exc)
        config = _unvalidated_config(row)
    return Mcp(
        id=row["id"],
        config=config,
        owner_id=row["owner_id"],
        created_by=row["created_by"],
        created_at=_parse_dt(row["created_at"]),
        config_error=error,
    )


def _map_integrity_error(exc: sqlite3.IntegrityError, config: McpConfig) -> Exception:
    msg = str(exc)
    if "mcps.name" in msg:
        return NameTakenError(config.name)
    if "mcps.host" in msg:  # UNIQUE (host, port) reports "mcps.host, mcps.port"
        return EndpointTakenError(f"{config.host}:{config.port}")
    return exc


class McpStore:
    def __init__(self, db: Database, clock: Clock, users: UserStore) -> None:
        self._db = db
        self._clock = clock
        self._users = users

    def insert(
        self, conn: sqlite3.Connection, config: McpConfig, owner_id: int, created_by: int
    ) -> int:
        """Insert inside the caller's transaction; the caller owns commit and rollback."""
        try:
            row_id = conn.execute(
                "INSERT INTO mcps (name, host, port, config, owner_id, created_by, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    config.name,
                    config.host,
                    config.port,
                    config.model_dump_json(),
                    owner_id,
                    created_by,
                    self._clock.now().isoformat(),
                ),
            ).lastrowid
            assert row_id is not None  # an INSERT always sets lastrowid
            return row_id
        except sqlite3.IntegrityError as exc:
            mapped = _map_integrity_error(exc, config)
            if mapped is exc:
                raise
            raise mapped from exc

    def create(self, config: McpConfig, owner_id: int) -> Mcp:
        with self._db.transaction() as conn:
            mcp_id = self.insert(conn, config, owner_id, owner_id)
        return self._require(mcp_id)

    def get(self, mcp_id: int) -> Mcp | None:
        rows = self._db.query("SELECT * FROM mcps WHERE id = ?", (mcp_id,))
        return _to_mcp(rows[0]) if rows else None

    def list(self) -> list[Mcp]:
        return [_to_mcp(r) for r in self._db.query("SELECT * FROM mcps ORDER BY name, id")]

    def update(self, mcp_id: int, patch: Mapping[str, Any]) -> tuple[Mcp, Mcp]:
        """Merge ``patch`` into the stored config; returns ``(before, after)``.

        Raises ``McpNotFoundError`` for an unknown id and ``pydantic.ValidationError`` for an
        invalid result (unknown keys included); a failed update leaves the row untouched.
        """
        new_config: McpConfig | None = None
        try:
            with self._db.transaction() as conn:
                row = conn.execute("SELECT * FROM mcps WHERE id = ?", (mcp_id,)).fetchone()
                if row is None:
                    raise McpNotFoundError(mcp_id)
                before = _to_mcp(row)
                # warnings=False: a stored config that fails validation (Mcp.config_error) is
                # unvalidated and may not match the field types; the merge must then fix it.
                new_config = McpConfig.model_validate(
                    {**before.config.model_dump(warnings=False), **patch}
                )
                conn.execute(
                    "UPDATE mcps SET name = ?, host = ?, port = ?, config = ? WHERE id = ?",
                    (
                        new_config.name,
                        new_config.host,
                        new_config.port,
                        new_config.model_dump_json(),
                        mcp_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if new_config is None:  # unreachable: only the UPDATE raises it
                raise
            mapped = _map_integrity_error(exc, new_config)
            if mapped is exc:
                raise
            raise mapped from exc
        return before, self._require(mcp_id)

    def set_owner(self, mcp_id: int, owner_id: int) -> Mcp:
        if self._db.execute_rowcount(
            "UPDATE mcps SET owner_id = ? WHERE id = ?", (owner_id, mcp_id)
        ) == 0:
            raise McpNotFoundError(mcp_id)
        return self._require(mcp_id)

    def set_maintenance(self, mcp_id: int, on: bool) -> Mcp:
        return self.update(mcp_id, {"maintenance": on})[1]

    def delete(self, mcp_id: int) -> None:
        """Delete the MCP; scripts, versions, minutes, transitions and actions cascade."""
        if self._db.execute_rowcount("DELETE FROM mcps WHERE id = ?", (mcp_id,)) == 0:
            raise McpNotFoundError(mcp_id)

    def owner_counts(self) -> dict[int, int]:
        """MCPs per effective owner: only active users appear (a deactivated owner has no effective MCPs)."""
        rows = self._db.query(
            "SELECT m.owner_id AS owner_id, COUNT(*) AS n FROM mcps m"
            " JOIN users u ON u.id = m.owner_id WHERE u.active = 1 GROUP BY m.owner_id"
        )
        return {r["owner_id"]: r["n"] for r in rows}

    def effective_owner_id(self, mcp: Mcp) -> int | None:
        """The owner's id while the owner is an active user, else None (no owner)."""
        if mcp.owner_id is None:
            return None
        owner = self._users.get(mcp.owner_id)
        return owner.id if owner is not None and owner.active else None

    def _require(self, mcp_id: int) -> Mcp:
        mcp = self.get(mcp_id)
        if mcp is None:
            raise McpNotFoundError(mcp_id)
        return mcp
