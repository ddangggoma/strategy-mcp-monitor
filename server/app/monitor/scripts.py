from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from app.clock import Clock
from app.db import Database
from app.monitor.models import Mcp, McpConfig
from app.monitor.store import McpNotFoundError, McpStore, _parse_dt
from app.paths import AppPaths

SCRIPT_EXTS = (".ps1", ".bat", ".cmd")
SCRIPT_KINDS = ("start", "stop", "restart")
REQUIRED_KINDS = ("start", "stop")
MAX_SCRIPT_BYTES = 65_536
_UTF8_BOM = b"\xef\xbb\xbf"


class ScriptValidationError(Exception):
    """``code`` is one of scripts_required, script_too_large, script_encoding, script_empty, validation."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ScriptRequiredError(Exception):
    """start/stop scripts cannot be deleted."""


class ScriptNotFoundError(Exception):
    pass


class ScriptUpload(NamedTuple):
    ext: str
    content: str


@dataclass(frozen=True)
class PreparedScript:
    kind: str
    ext: str
    text: str  # normalized content (CRLF, trailing CRLF)
    data: bytes  # exactly what is written to disk
    sha256: str  # sha256(data)


@dataclass(frozen=True)
class ScriptInfo:
    kind: str
    ext: str
    sha256: str
    version: int
    updated_at: datetime
    updated_by: int | None
    path: Path


@dataclass(frozen=True)
class ScriptVersion:
    version: int
    ext: str | None
    sha256: str | None
    content: str | None
    author_id: int | None
    created_at: datetime

    @property
    def deleted(self) -> bool:
        return self.sha256 is None


def prepare_script(kind: str, upload: ScriptUpload) -> PreparedScript:
    """Validate and normalize an upload: CRLF, UTF-8 BOM for .ps1, OEM code page for .bat/.cmd."""
    ext = upload.ext.lower() if isinstance(upload.ext, str) else upload.ext
    if kind not in SCRIPT_KINDS or ext not in SCRIPT_EXTS or not isinstance(upload.content, str):
        raise ScriptValidationError("validation")
    if not upload.content.strip():
        raise ScriptValidationError("script_empty")
    text = upload.content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    if not text.endswith("\r\n"):
        text += "\r\n"
    try:
        if ext == ".ps1":
            data = _UTF8_BOM + text.encode("utf-8")
        else:
            data = text.encode("oem")  # strict: characters outside the OEM code page are rejected
    except UnicodeEncodeError:
        raise ScriptValidationError("script_encoding") from None
    if len(data) > MAX_SCRIPT_BYTES:
        raise ScriptValidationError("script_too_large")
    return PreparedScript(kind, ext, text, data, hashlib.sha256(data).hexdigest())


def _check_kind(kind: str) -> None:
    if kind not in SCRIPT_KINDS:
        raise ScriptValidationError("validation")


class ScriptStore:
    def __init__(self, db: Database, paths: AppPaths, clock: Clock, mcps: McpStore) -> None:
        self._db = db
        self._paths = paths
        self._clock = clock
        self._mcps = mcps

    # ---- paths (ids are ints and kinds/exts come from fixed sets: no traversal possible) ----

    def _dir(self, mcp_id: int) -> Path:
        return self._paths.scripts_dir / str(int(mcp_id))

    def _path(self, mcp_id: int, kind: str, ext: str) -> Path:
        return self._dir(mcp_id) / f"{kind}{ext}"

    # ---- reads ----

    def get(self, mcp_id: int, kind: str) -> ScriptInfo | None:
        rows = self._db.query(
            "SELECT * FROM mcp_scripts WHERE mcp_id = ? AND kind = ?", (mcp_id, kind)
        )
        return self._to_info(rows[0]) if rows else None

    def list(self, mcp_id: int) -> list[ScriptInfo]:
        rows = self._db.query("SELECT * FROM mcp_scripts WHERE mcp_id = ?", (mcp_id,))
        infos = [self._to_info(r) for r in rows]
        return sorted(infos, key=lambda i: SCRIPT_KINDS.index(i.kind))

    def content(self, mcp_id: int, kind: str) -> str | None:
        rows = self._db.query(
            "SELECT v.content FROM mcp_scripts s JOIN mcp_script_versions v"
            " ON v.mcp_id = s.mcp_id AND v.kind = s.kind AND v.version = s.version"
            " WHERE s.mcp_id = ? AND s.kind = ?",
            (mcp_id, kind),
        )
        return rows[0]["content"] if rows else None

    def versions(self, mcp_id: int, kind: str) -> list[ScriptVersion]:
        rows = self._db.query(
            "SELECT * FROM mcp_script_versions WHERE mcp_id = ? AND kind = ? ORDER BY version DESC",
            (mcp_id, kind),
        )
        return [self._to_version(r) for r in rows]

    def version(self, mcp_id: int, kind: str, version: int) -> ScriptVersion | None:
        rows = self._db.query(
            "SELECT * FROM mcp_script_versions WHERE mcp_id = ? AND kind = ? AND version = ?",
            (mcp_id, kind, version),
        )
        return self._to_version(rows[0]) if rows else None

    # ---- writes ----

    def create_mcp(
        self, config: McpConfig, owner_id: int, uploads: Mapping[str, ScriptUpload]
    ) -> Mcp:
        """Create the MCP and its scripts atomically: any failure leaves no row and no files."""
        if any(k not in uploads for k in REQUIRED_KINDS):
            raise ScriptValidationError("scripts_required")
        prepared = [prepare_script(kind, uploads[kind]) for kind in SCRIPT_KINDS if kind in uploads]
        if len(prepared) != len(uploads):  # a kind outside the fixed set
            raise ScriptValidationError("validation")
        directory: Path | None = None
        try:
            with self._db.transaction() as conn:
                mcp_id = self._mcps.insert(conn, config, owner_id, owner_id)
                directory = self._dir(mcp_id)
                directory.mkdir(parents=True, exist_ok=True)
                # The id is only known now, so unlike put/revert the tmp files are written
                # inside the transaction (after the insert); os.replace stays the last step.
                for p in prepared:
                    self._write_version(conn, mcp_id, p, owner_id)
        except BaseException:
            if directory is not None:
                shutil.rmtree(directory, ignore_errors=True)
            raise
        return self._require_mcp(mcp_id)

    def put(self, mcp_id: int, kind: str, upload: ScriptUpload, author_id: int | None) -> ScriptInfo:
        _check_kind(kind)
        prepared = prepare_script(kind, upload)
        self._require_mcp(mcp_id)
        return self._publish(mcp_id, prepared, author_id)

    def delete(self, mcp_id: int, kind: str, author_id: int | None) -> None:
        _check_kind(kind)
        if kind in REQUIRED_KINDS:
            raise ScriptRequiredError(kind)
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT ext FROM mcp_scripts WHERE mcp_id = ? AND kind = ?", (mcp_id, kind)
            ).fetchone()
            if row is None:
                raise ScriptNotFoundError(f"{mcp_id}/{kind}")
            conn.execute(
                "INSERT INTO mcp_script_versions"
                " (mcp_id, kind, version, ext, content, sha256, author_id, created_at)"
                " VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?)",
                (mcp_id, kind, self._next_version(conn, mcp_id, kind), author_id,
                 self._clock.now().isoformat()),
            )
            conn.execute("DELETE FROM mcp_scripts WHERE mcp_id = ? AND kind = ?", (mcp_id, kind))
        # The DB no longer references the file; a leftover is harmless, so a failure here is ignored.
        with contextlib.suppress(OSError):
            self._path(mcp_id, kind, row["ext"]).unlink(missing_ok=True)

    def revert(self, mcp_id: int, kind: str, version: int, author_id: int | None) -> ScriptInfo:
        """Re-publish an earlier version's content as a new version."""
        _check_kind(kind)
        target = self.version(mcp_id, kind, version)
        if target is None:
            raise ScriptNotFoundError(f"{mcp_id}/{kind}@{version}")
        if target.deleted or target.ext is None or target.content is None:
            raise ScriptValidationError("validation")
        prepared = prepare_script(kind, ScriptUpload(target.ext, target.content))
        if prepared.sha256 != target.sha256:  # normalization is idempotent; a mismatch means corruption
            raise ScriptValidationError("validation")
        return self._publish(mcp_id, prepared, author_id)

    def remove_dir(self, mcp_id: int) -> None:
        shutil.rmtree(self._dir(mcp_id), ignore_errors=True)

    # ---- internals ----

    def _publish(self, mcp_id: int, p: PreparedScript, author_id: int | None) -> ScriptInfo:
        """tmp file -> (version row + upsert + os.replace) in one transaction -> drop other-ext files."""
        directory = self._dir(mcp_id)
        directory.mkdir(parents=True, exist_ok=True)
        tmp = self._write_tmp(mcp_id, p)
        try:
            with self._db.transaction() as conn:
                self._record(conn, mcp_id, p, author_id, tmp)
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
            raise
        for other in SCRIPT_EXTS:
            if other != p.ext:
                with contextlib.suppress(OSError):
                    self._path(mcp_id, p.kind, other).unlink(missing_ok=True)
        info = self.get(mcp_id, p.kind)
        assert info is not None
        return info

    def _write_version(
        self, conn: sqlite3.Connection, mcp_id: int, p: PreparedScript, author_id: int | None
    ) -> None:
        self._record(conn, mcp_id, p, author_id, self._write_tmp(mcp_id, p))

    def _write_tmp(self, mcp_id: int, p: PreparedScript) -> Path:
        tmp = self._path(mcp_id, p.kind, p.ext + ".tmp")
        with open(tmp, "wb") as f:
            f.write(p.data)
            f.flush()
            os.fsync(f.fileno())
        return tmp

    def _record(
        self, conn: sqlite3.Connection, mcp_id: int, p: PreparedScript, author_id: int | None,
        tmp: Path,
    ) -> None:
        now = self._clock.now().isoformat()
        version = self._next_version(conn, mcp_id, p.kind)
        conn.execute(
            "INSERT INTO mcp_script_versions"
            " (mcp_id, kind, version, ext, content, sha256, author_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (mcp_id, p.kind, version, p.ext, p.text, p.sha256, author_id, now),
        )
        conn.execute(
            "INSERT INTO mcp_scripts (mcp_id, kind, ext, sha256, version, updated_at, updated_by)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (mcp_id, kind) DO UPDATE SET ext = excluded.ext,"
            " sha256 = excluded.sha256, version = excluded.version,"
            " updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (mcp_id, p.kind, p.ext, p.sha256, version, now, author_id),
        )
        # Last statement: if the replace fails the transaction rolls back and the old file stays.
        os.replace(tmp, self._path(mcp_id, p.kind, p.ext))

    @staticmethod
    def _next_version(conn: sqlite3.Connection, mcp_id: int, kind: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM mcp_script_versions WHERE mcp_id = ? AND kind = ?",
            (mcp_id, kind),
        ).fetchone()
        return int(row[0]) + 1

    def _require_mcp(self, mcp_id: int) -> Mcp:
        mcp = self._mcps.get(mcp_id)
        if mcp is None:
            raise McpNotFoundError(mcp_id)
        return mcp

    def _to_info(self, row: sqlite3.Row) -> ScriptInfo:
        return ScriptInfo(
            kind=row["kind"],
            ext=row["ext"],
            sha256=row["sha256"],
            version=row["version"],
            updated_at=_parse_dt(row["updated_at"]),
            updated_by=row["updated_by"],
            path=self._path(row["mcp_id"], row["kind"], row["ext"]),
        )

    @staticmethod
    def _to_version(row: sqlite3.Row) -> ScriptVersion:
        return ScriptVersion(
            version=row["version"],
            ext=row["ext"],
            sha256=row["sha256"],
            content=row["content"],
            author_id=row["author_id"],
            created_at=_parse_dt(row["created_at"]),
        )
