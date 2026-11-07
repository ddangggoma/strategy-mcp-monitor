"""``activity.command`` ``script_block`` lines from PowerShell 4104 (script block logging).

PowerShell splits a long script block into several 4104 events (``MessageNumber`` of
``MessageTotal``); ``ScriptBlockAssembler`` joins them, gives up waiting after ``max_wait_sec`` and
cuts the text at ``max_chars`` code points (V14). It holds at most ``max_chars`` (+1) of text per
block and ``max_pending`` blocks (the oldest is written early as incomplete; M6). Everything here
runs on the loop thread; the account name comes from the cache the watcher thread fills.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from app.activity.context import ActivityContext
from app.activity.process import SYSTEM_SIDS
from app.clock import Clock
from app.collect.manager import Collectors
from app.logstore.writer import LogSink
from app.win import accounts
from app.win.eventlog import EventRecord

PWSH_CHANNEL = "PowerShellCore/Operational"


@dataclass(frozen=True)
class ScriptBlock:
    at: datetime
    shell: Literal["powershell", "pwsh"]
    script_block_id: str
    text: str
    path: str | None
    parts: int
    total: int
    truncated: bool
    incomplete: bool
    pid: int | None
    user_sid: str | None
    record_id: int


@dataclass
class _Pending:
    first: EventRecord
    """The first fragment received: the block's ``at``, ``pid``, ``user_sid`` and ``record_id``."""
    received: datetime
    total: int
    path: str | None
    texts: dict[int, str] = field(default_factory=dict)
    chars: int = 0


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value else default
    except ValueError:
        return default


class ScriptBlockAssembler:
    def __init__(
        self, *, max_wait_sec: float = 5.0, max_chars: int = 65_536, max_pending: int = 256
    ) -> None:
        self._max_wait = timedelta(seconds=max_wait_sec)
        self._max_chars = max_chars
        self._max_pending = max(1, max_pending)
        self._pending: dict[tuple[str, str], _Pending] = {}

    def add(self, r: EventRecord, now: datetime) -> list[ScriptBlock]:
        """Take one 4104 fragment; returns the block once all its fragments are in (else ``[]``).
        Fragments of SYSTEM/LocalService/NetworkService are dropped."""
        if r.event_id != 4104 or r.user_sid in SYSTEM_SIDS:
            return []
        d = r.data
        number = _int(d.get("MessageNumber"), 1)
        total = max(_int(d.get("MessageTotal"), 1), 1)
        key = (r.channel, d.get("ScriptBlockId") or "")
        out: list[ScriptBlock] = []
        pending = self._pending.get(key)
        if pending is None:
            while len(self._pending) >= self._max_pending:  # the oldest goes out early
                oldest = next(iter(self._pending))
                out.append(self._block(oldest, self._pending.pop(oldest), incomplete=True))
            pending = self._pending[key] = _Pending(r, now, total, d.get("Path") or None)
        if number not in pending.texts:
            # Keep one character past the limit, so ``_block`` still sees that it was cut.
            room = max(0, self._max_chars + 1 - pending.chars)
            text = (d.get("ScriptBlockText") or "")[:room]
            pending.texts[number] = text
            pending.chars += len(text)
        if pending.path is None:
            pending.path = d.get("Path") or None
        if len(pending.texts) < pending.total:
            return out
        del self._pending[key]
        out.append(self._block(key, pending, incomplete=False))
        return out

    def expire(self, now: datetime) -> list[ScriptBlock]:
        """Blocks still missing fragments ``max_wait_sec`` after their first one, joined from what
        arrived (``incomplete=True``)."""
        due = [k for k, p in self._pending.items() if now - p.received >= self._max_wait]
        return [self._block(k, self._pending.pop(k), incomplete=True) for k in due]

    def flush(self) -> list[ScriptBlock]:
        """Every pending block, now, as incomplete (the service is stopping)."""
        pending, self._pending = self._pending, {}
        return [self._block(k, p, incomplete=True) for k, p in pending.items()]

    def _block(self, key: tuple[str, str], p: _Pending, *, incomplete: bool) -> ScriptBlock:
        text = "".join(p.texts[n] for n in sorted(p.texts))
        truncated = len(text) > self._max_chars
        channel, block_id = key
        return ScriptBlock(
            at=p.first.time_created,
            shell="pwsh" if channel == PWSH_CHANNEL else "powershell",
            script_block_id=block_id,
            text=text[: self._max_chars] if truncated else text,
            path=p.path,
            parts=len(p.texts),
            total=p.total,
            truncated=truncated,
            incomplete=incomplete,
            pid=p.first.pid,
            user_sid=p.first.user_sid,
            record_id=p.first.record_id,
        )


class PowerShellHandler:
    """Event log handler (``eventlog:powershell``, ``eventlog:pwsh``): one ``activity.command``
    ``script_block`` line per assembled block. ``tick()`` must run about once a second."""

    def __init__(
        self,
        context: ActivityContext,
        log: LogSink,
        clock: Clock,
        *,
        sid_to_account: Callable[[str], str | None] = accounts.cached_account,
        assembler: ScriptBlockAssembler | None = None,
    ) -> None:
        self._context = context
        self._log = log
        self._clock = clock
        self._sid_to_account = sid_to_account
        self._assembler = assembler if assembler is not None else ScriptBlockAssembler()

    def __call__(self, records: list[EventRecord]) -> None:
        for r in records:
            self._emit(self._assembler.add(r, self._clock.now()))

    def tick(self) -> None:
        self._emit(self._assembler.expire(self._clock.now()))

    def flush(self) -> None:
        self._emit(self._assembler.flush())

    def _emit(self, blocks: list[ScriptBlock]) -> None:
        for b in blocks:
            user = self._sid_to_account(b.user_sid) if b.user_sid else None
            self._log.emit(
                "activity.command",
                at=b.at,
                event="script_block",
                shell=b.shell,
                text=b.text,
                script_block_id=b.script_block_id,
                path=b.path,
                parts=b.parts,
                truncated=b.truncated,
                incomplete=b.incomplete,
                pid=b.pid,
                source="eventlog:4104",
                record_id=b.record_id,
                **self._context.fields(self._context.session_of(b.pid), user=user),
            )


async def expire_every(
    handler: PowerShellHandler, collectors: Collectors, *, interval_sec: float = 1.0
) -> None:
    """The ``powershell-expire`` collector task: ``tick()`` every ``interval_sec``; a failing tick
    is logged (``collector.handler_failed``) and the loop goes on. On cancel (service stop) the
    blocks still waiting for fragments are written as incomplete."""
    try:
        while True:
            await asyncio.sleep(interval_sec)
            try:
                handler.tick()
            except Exception as exc:
                collectors.handler_failed("powershell-expire", exc)
    finally:
        try:
            handler.flush()
        except Exception as exc:
            collectors.handler_failed("powershell-expire", exc)
