from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db import Database

_KEY = "global"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    ping_interval_sec: int = Field(default=5, ge=1, le=300)
    issue_check_interval_sec: int = Field(default=10, ge=5, le=60)
    confirm_interval_sec: int = Field(default=1, ge=1, le=10)
    log_retention_days: int = Field(default=180, ge=7, le=3650)
    log_compress_after_days: int = Field(default=30, ge=1)
    service_start_type: Literal["auto", "delayed-auto", "manual"] = "delayed-auto"
    otp_provider: Literal["dummy"] = "dummy"

    @model_validator(mode="after")
    def _compress_within_retention(self) -> Self:
        if self.log_compress_after_days > self.log_retention_days:
            raise ValueError("log_compress_after_days must be <= log_retention_days")
        return self


class SettingsStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self) -> Settings:
        rows = self._db.query("SELECT value FROM settings WHERE key = ?", (_KEY,))
        if not rows:
            return Settings()
        return Settings.model_validate_json(rows[0]["value"])

    def update(self, patch: Mapping[str, Any]) -> Settings:
        # Read-merge-validate-write in one transaction so concurrent updates
        # cannot lose each other's writes. Validation errors roll back.
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (_KEY,)
            ).fetchone()
            current = Settings.model_validate_json(row["value"]) if row else Settings()
            merged = Settings.model_validate({**current.model_dump(), **patch})
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (_KEY, merged.model_dump_json()),
            )
        return merged
