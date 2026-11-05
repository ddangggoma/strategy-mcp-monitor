"""Versioned pre-notice message: append-only ``notice_versions`` plus the built-in text as version 0.

A version never changes once written. Saving or reverting to content identical to the current
one creates nothing. Reverting copies the old content into a new version (``reverted_from``).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.clock import Clock
from app.db import Database
from app.notice.content import NoticeContent
from app.notice.defaults import DEFAULT_NOTICE

TITLE_MAX = 80
BODY_MAX = 4000
BUTTON_MAX = 20

# C0 (minus TAB, and minus LF where a newline is meant), DEL, C1, and lone surrogates (SQLite cannot store them).
_CONTROL_SINGLE_LINE = re.compile("[\x00-\x08\x0a-\x1f\x7f-\x9f\ud800-\udfff]")
_CONTROL_MULTI_LINE = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\ud800-\udfff]")

_COLUMNS = "version, title, body, button_text, author_id, created_at, reverted_from"


class NoticeNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class NoticeVersion:
    version: int
    content: NoticeContent
    author_id: int | None
    created_at: datetime | None
    reverted_from: int | None


_DEFAULT_VERSION = NoticeVersion(0, DEFAULT_NOTICE, None, None, None)


def _single_line(value: str, limit: int) -> str:
    if _CONTROL_SINGLE_LINE.search(value):
        raise ValueError("control characters are not allowed")
    value = value.strip()
    if not 1 <= len(value) <= limit:
        raise ValueError(f"must be 1-{limit} characters")
    return value


class NoticeBody(BaseModel):
    """Request body of ``PUT /api/notice``; validation normalizes the text."""

    model_config = ConfigDict(extra="forbid", strict=True)

    title: str
    body: str
    button_text: str

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _single_line(value, TITLE_MAX)

    @field_validator("button_text")
    @classmethod
    def _button_text(cls, value: str) -> str:
        return _single_line(value, BUTTON_MAX)

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        value = value.replace("\r\n", "\n").replace("\r", "\n")
        if _CONTROL_MULTI_LINE.search(value):  # checked before rstrip, which would erase some of them
            raise ValueError("control characters are not allowed")
        lines = [line.rstrip() for line in value.split("\n")]
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        text = "\n".join(lines)
        if not 1 <= len(text) <= BODY_MAX:
            raise ValueError(f"must be 1-{BODY_MAX} characters")
        return text

    def to_content(self) -> NoticeContent:
        return NoticeContent(self.title, self.body, self.button_text)


def content_sha256(content: NoticeContent) -> str:
    """Digest of the three fields (unambiguous field boundaries) for audit lines, which never carry the text."""
    encoded = json.dumps(
        [content.title, content.body, content.button_text], ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _from_row(row: sqlite3.Row) -> NoticeVersion:
    return NoticeVersion(
        version=row["version"],
        content=NoticeContent(row["title"], row["body"], row["button_text"]),
        author_id=row["author_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        reverted_from=row["reverted_from"],
    )


class NoticeStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    # ---- reads ---------------------------------------------------------------------

    def current(self) -> NoticeVersion:
        rows = self._db.query(
            f"SELECT {_COLUMNS} FROM notice_versions ORDER BY version DESC LIMIT 1"
        )
        return _from_row(rows[0]) if rows else _DEFAULT_VERSION

    def version(self, version: int) -> NoticeVersion | None:
        if version == 0:
            return _DEFAULT_VERSION
        rows = self._db.query(
            f"SELECT {_COLUMNS} FROM notice_versions WHERE version = ?", (version,)
        )
        return _from_row(rows[0]) if rows else None

    def versions(self, limit: int = 100) -> list[NoticeVersion]:
        """Stored versions, newest first (the built-in version 0 is not part of the history)."""
        rows = self._db.query(
            f"SELECT {_COLUMNS} FROM notice_versions ORDER BY version DESC LIMIT ?", (limit,)
        )
        return [_from_row(r) for r in rows]

    # ---- writes --------------------------------------------------------------------

    def save(self, content: NoticeContent, author_id: int | None) -> tuple[NoticeVersion, bool]:
        """Store ``content`` as a new version; ``(current, False)`` when it equals the current text."""
        return self._append(content, author_id, None)

    def revert(self, version: int, author_id: int | None) -> tuple[NoticeVersion, bool]:
        """Make the content of ``version`` (0 = built-in) current by appending a new version."""
        return self._append(None, author_id, version)

    def _append(
        self, content: NoticeContent | None, author_id: int | None, revert_of: int | None
    ) -> tuple[NoticeVersion, bool]:
        with self._db.transaction() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM notice_versions ORDER BY version DESC LIMIT 1"
            ).fetchone()
            current = _from_row(row) if row is not None else _DEFAULT_VERSION
            if revert_of is not None:
                if revert_of == 0:
                    content = DEFAULT_NOTICE
                else:
                    found = conn.execute(
                        "SELECT title, body, button_text FROM notice_versions WHERE version = ?",
                        (revert_of,),
                    ).fetchone()
                    if found is None:
                        raise NoticeNotFoundError(revert_of)
                    content = NoticeContent(found["title"], found["body"], found["button_text"])
            assert content is not None
            if content == current.content:
                return current, False
            created = self._clock.now()
            new_version = current.version + 1  # the highest stored version, read in this transaction
            conn.execute(
                "INSERT INTO notice_versions"
                " (version, title, body, button_text, author_id, created_at, reverted_from)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (new_version, content.title, content.body, content.button_text, author_id,
                 created.isoformat(), revert_of),
            )
            return NoticeVersion(new_version, content, author_id, created, revert_of), True
