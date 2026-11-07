"""Reading JSONL log files in resumable chunks (plain files being appended to, and immutable ``.gz``).

Lines end with ``\\n`` only: the writer escapes nothing else, so U+2028/U+2029 and ``\\x1c``-``\\x1e``
inside a string value stay inside the line (``str.splitlines`` would cut there). Offsets are byte
offsets in the uncompressed stream.
"""
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

MAX_LINE_BYTES = 4 * 1024 * 1024
CHUNK_BYTES = 8 * 1024 * 1024
EXTEND_BYTES = 1024 * 1024  # step for reading on when a chunk holds no complete line


@dataclass(frozen=True)
class Chunk:
    lines: list[tuple[int, bytes]]  # (line start offset, line bytes without the newline)
    next_offset: int
    eof: bool
    oversized: int


def _split(data: bytes, base: int) -> tuple[list[tuple[int, bytes]], int, int]:
    """Complete non-empty lines of ``data`` with offsets (``base`` = offset of ``data[0]``), the bytes
    used (through the last newline) and how many lines were longer than ``MAX_LINE_BYTES``."""
    lines: list[tuple[int, bytes]] = []
    oversized = 0
    start = 0
    limit = MAX_LINE_BYTES
    while (nl := data.find(b"\n", start)) != -1:
        if nl - start > limit:
            oversized += 1
        elif nl > start:
            lines.append((base + start, data[start:nl]))
        start = nl + 1
    return lines, start, oversized


def split_lines(data: bytes) -> tuple[list[bytes], int]:
    """The complete non-empty lines of ``data`` (split on ``\\n`` only) and the bytes consumed,
    through the last ``\\n``. The fragment after the last ``\\n`` is not returned."""
    lines: list[bytes] = []
    start = 0
    while (nl := data.find(b"\n", start)) != -1:
        if nl > start:
            lines.append(data[start:nl])
        start = nl + 1
    return lines, start


def open_log(path: Path) -> BinaryIO:
    """Open a log file for binary reading; ``.gz`` files are decompressed on the fly."""
    if path.name.endswith(".gz"):
        return gzip.open(path, "rb")  # type: ignore[return-value]
    return open(path, "rb")


def read_chunk(fh: BinaryIO, offset: int, max_bytes: int = CHUNK_BYTES, *, final: bool = False) -> Chunk:
    """Read the complete lines from ``offset``, about ``max_bytes`` of them.

    If the read holds no newline and the file goes on, reading continues ``EXTEND_BYTES`` at a time
    to the next newline or the end. A line longer than ``MAX_LINE_BYTES`` is skipped (never held in
    memory beyond that) and counted in ``oversized``. The fragment after the last newline is left for
    the next call, unless ``final`` (an immutable file) and the read reached the end: then it is the
    last line. ``next_offset`` is where the next call starts.
    """
    fh.seek(offset)
    data = fh.read(max_bytes)
    eof = len(data) < max_bytes
    base = offset  # offset of data[0]
    oversized = 0
    while b"\n" not in data and not eof:
        if len(data) <= MAX_LINE_BYTES:
            more = fh.read(EXTEND_BYTES)
            eof = len(more) < EXTEND_BYTES
            data += more
            continue
        # One line already longer than the limit: skip to its newline without keeping it.
        pos = base + len(data)
        while True:
            more = fh.read(EXTEND_BYTES)
            eof = len(more) < EXTEND_BYTES
            nl = more.find(b"\n")
            if nl != -1:
                oversized += 1
                base, data = pos + nl + 1, more[nl + 1:]
                break
            pos += len(more)
            if eof:
                if final:  # an immutable file ends inside the long line: it is done
                    return Chunk([], pos, True, oversized + 1)
                return Chunk([], base, True, oversized)  # the writer may still finish it
    lines, used, long_lines = _split(data, base)
    oversized += long_lines
    tail = len(data) - used
    if final and eof and tail:
        if tail > MAX_LINE_BYTES:
            oversized += 1
        else:
            lines.append((base + used, data[used:]))
        used = len(data)
    return Chunk(lines, base + used, eof, oversized)


def parse_line(raw: bytes) -> dict[str, Any] | None:
    """The event of one line, or None unless it is a JSON object with an ISO ``ts`` that has an
    offset and a string ``cat``."""
    try:
        obj = json.loads(raw.decode("utf-8", "replace"))
    except (ValueError, RecursionError):
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("cat"), str):
        return None
    ts = obj.get("ts")
    if not isinstance(ts, str):
        return None
    try:
        at = datetime.fromisoformat(ts)
        if at.tzinfo is None or at.utcoffset() is None:
            return None
        at.timestamp()  # normalize() needs it; out-of-range values are rejected here
    except (ValueError, OverflowError, OSError):
        return None
    return obj
