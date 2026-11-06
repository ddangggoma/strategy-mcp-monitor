"""The session agents' side of the Local API (V4, ruling C2): one slot per RDP session.

Each launch gets a fresh token (``mint``); the hub keeps only its sha256. Every request must also
come from a TCP peer whose Windows session — resolved by the server from the connection, never
taken from the request — is the slot's session; a valid token used from anywhere else is an
``agent_impersonation`` tamper event. The agent long-polls ``next`` for commands
(``show_notice``/``close_notice``/``exit``), sends heartbeats, window/idle events, and reports
a notice window the user closed before acknowledging it.

A slot shows a display at most once per token (ruling F09): the display listener (``created``)
and the agent supervisor (``ensure`` for a live agent) both ask to show the same new display on a
reconnect, and only the first issues a token. A closed window, a new hello or a new agent (slot)
allows the next showing.

Loop thread only (it reads the database through ``NoticeDisplays``).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, NoReturn

from app.activity.context import ActivityContext
from app.activity.tamper import MISUSE_REPORT_SEC, TamperMonitor
from app.clock import Clock
from app.logstore.writer import LogSink
from app.notice.displays import Display, DisplayEvent, NoticeDisplays
from app.sessions.tracker import SessionTracker
from app.win.peer import PeerInfo

if TYPE_CHECKING:
    from app.web.agent_api import IdleEventIn, WindowEventIn

AGENT_TOKEN_HEADER: Final = "X-Agent-Token"
AGENT_NONCE_HEADER: Final = "X-Agent-Nonce"
SERVER_PROOF_HEADER: Final = "X-Server-Proof"
NONCE_MAX: Final = 128
HELLO: Final[dict[str, Any]] = {
    "heartbeat_sec": 5,
    "events_max": 200,
    "idle_threshold_sec": 300,
    "window_events": True,  # ruling F13: False under --activity off
}
CLOCK_SKEW_SEC: Final = 300  # V28


class AgentAuthError(Exception):
    """401 ``login_required`` (no or unknown token), 403 ``forbidden`` (a peer in another
    session) or 503 ``unavailable`` (the peer could not be resolved: the agent retries)."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass(eq=False)
class AgentSlot:
    session_id: int
    user: str
    token_sha256: str
    minted_at: datetime
    server_key: str = field(default_factory=lambda: secrets.token_hex(32), repr=False)
    """Hex key handed to the agent at launch (never sent over the wire): the server proves it is
    the real service by answering each request's nonce with ``HMAC-SHA256(key, nonce)`` (I1)."""
    pid: int | None = None
    hello_at: datetime | None = None
    last_seen: datetime | None = None
    version: str | None = None
    commands: deque[dict[str, Any]] = field(default_factory=deque)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    notice_display: int | None = None
    """The display whose ``show_notice`` is queued or delivered on this slot (F09)."""


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def server_proof(server_key: str, nonce: str) -> str:
    """What the agent expects in ``X-Server-Proof`` for the ``X-Agent-Nonce`` it sent."""
    return hmac.new(bytes.fromhex(server_key), nonce.encode("utf-8"), hashlib.sha256).hexdigest()


class AgentHub:
    def __init__(
        self,
        clock: Clock,
        log: LogSink,
        tamper: TamperMonitor,
        tracker: SessionTracker,
        displays: NoticeDisplays,
        context: ActivityContext,
        *,
        local_base_url: str = "http://127.0.0.1:8700",
        reshow_delay_sec: float = 1.0,
        window_events: bool = True,
    ) -> None:
        self._clock = clock
        self._log = log
        self._tamper = tamper
        self._tracker = tracker
        self._displays = displays
        self._context = context
        self._base = local_base_url.rstrip("/")
        self.reshow_delay_sec = reshow_delay_sec
        """Delay before a notice window the user closed is shown again (V15: 1 s)."""
        self.window_events = window_events
        """Whether agents report window/idle events (``CollectorConfig.activity``, ruling F13)."""
        self._slots: dict[int, AgentSlot] = {}
        self._by_digest: dict[str, AgentSlot] = {}

    # --- slots -----------------------------------------------------------------------------

    def configure(self, local_base_url: str) -> None:
        """The Local channel's base URL the notice page is opened from."""
        self._base = local_base_url.rstrip("/")

    def mint(self, session_id: int, user: str) -> str:
        """A new slot and token for a launch; the session's previous slot and token stop working."""
        self.revoke(session_id)
        token = secrets.token_urlsafe(32)
        slot = AgentSlot(session_id, user, _digest(token), self._clock.now())
        self._slots[session_id] = slot
        self._by_digest[slot.token_sha256] = slot
        return token

    def revoke(self, session_id: int) -> None:
        slot = self._slots.pop(session_id, None)
        if slot is None:
            return
        self._by_digest.pop(slot.token_sha256, None)
        slot.wake.set()  # end a pending long poll

    def slot(self, session_id: int) -> AgentSlot | None:
        return self._slots.get(session_id)

    def lookup(self, token: str | None) -> AgentSlot | None:
        """The slot of a live token (no peer check): cheap, so it runs before the peer scan (M1)."""
        return self._by_digest.get(_digest(token)) if token else None

    def proof(self, token: str | None, nonce: str | None) -> str | None:
        """``X-Server-Proof`` for a request with a live token and a sane nonce, else None."""
        if not nonce or len(nonce) > NONCE_MAX or not nonce.isascii():
            return None
        slot = self.lookup(token)
        return server_proof(slot.server_key, nonce) if slot is not None else None

    def authenticate(self, token: str | None, peer: PeerInfo | None) -> AgentSlot:
        slot = self.lookup(token)
        if slot is None:
            raise AgentAuthError(401, "login_required")
        if peer is None or peer.session_id is None:  # not evidence of anything (M2): retry later
            raise AgentAuthError(503, "unavailable")
        if peer.session_id != slot.session_id:
            self._impersonation(slot, peer)
        slot.last_seen = self._clock.now()
        return slot

    def hello(
        self, slot: AgentSlot, *, session_id: int, pid: int, version: str, peer: PeerInfo
    ) -> dict[str, Any]:
        if session_id != slot.session_id or pid != peer.pid:
            self._impersonation(slot, peer)
        now = self._clock.now()
        slot.pid, slot.version, slot.hello_at, slot.last_seen = pid, version, now, now
        slot.notice_display = None  # a (re)started agent shows nothing yet
        self.show_pending(slot.session_id)
        return {**HELLO, "window_events": self.window_events}

    def _impersonation(self, slot: AgentSlot, peer: PeerInfo) -> NoReturn:
        self._tamper.report_throttled(
            "agent_impersonation",
            key=(slot.session_id, peer.session_id),
            window_sec=MISUSE_REPORT_SEC,
            claimed_session=slot.session_id,
            peer_session=peer.session_id,
            peer_pid=peer.pid,
            peer_exe=peer.exe,
            peer_user=peer.user,
        )
        raise AgentAuthError(403, "forbidden")

    # --- commands --------------------------------------------------------------------------

    def show_pending(self, session_id: int) -> bool:
        """Queue ``show_notice`` with a fresh token for the session's open display, if the agent
        said hello and has not been sent that display yet. True when a command was queued."""
        slot = self._slots.get(session_id)
        if slot is None or slot.hello_at is None:
            return False
        display = self._displays.pending_for_session(session_id)
        if display is None or slot.notice_display == display.id:
            return False
        ticket = self._displays.issue(display.id)
        # A session has one open display: a queued show_notice of any display is out of date.
        self._drop(slot, lambda c: c["type"] == "show_notice")
        slot.commands.append({
            "type": "show_notice",
            "display_id": ticket.display_id,
            "attempt": ticket.attempt,
            "url": f"{self._base}/notice#d={ticket.display_id}&t={ticket.token}",
        })
        slot.notice_display = display.id
        slot.wake.set()
        return True

    def queue(self, session_id: int, command: dict[str, Any]) -> None:
        slot = self._slots.get(session_id)
        if slot is None:
            return
        slot.commands.append(command)
        slot.wake.set()

    async def next(self, slot: AgentSlot, timeout: float) -> dict[str, Any] | None:
        """The next command, waiting up to ``timeout`` seconds; None when there is none (or the
        slot was replaced meanwhile)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while self._slots.get(slot.session_id) is slot:
            if slot.commands:
                return slot.commands.popleft()
            slot.wake.clear()
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            try:
                await asyncio.wait_for(slot.wake.wait(), remaining)
            except TimeoutError:
                pass
        return None

    @staticmethod
    def _drop(slot: AgentSlot, unwanted: Callable[[dict[str, Any]], bool]) -> None:
        kept = [c for c in slot.commands if not unwanted(c)]
        slot.commands.clear()
        slot.commands.extend(kept)

    # --- reports from the agent ------------------------------------------------------------

    def heartbeat(self, slot: AgentSlot, *, idle_sec: int | None, locked: bool | None) -> None:
        """Liveness only: the board's idle time and lock state come from WTS (V26)."""
        slot.last_seen = self._clock.now()

    def events(self, slot: AgentSlot, events: Sequence[WindowEventIn | IdleEventIn]) -> None:
        """``activity.window`` / ``activity.idle`` lines at the event time (V28: clamped to now
        with ``clock_skew`` when the agent's clock is more than 300 s off)."""
        if not self.window_events:
            return
        now = self._clock.now()
        ctx = self._context.fields(slot.session_id)
        limit = timedelta(seconds=CLOCK_SKEW_SEC)
        for e in events:
            at = e.at
            skew: dict[str, Any] = {}
            if abs(at - now) > limit:
                at, skew = now, {"clock_skew": True}
            if e.type == "idle" or e.type == "active":
                self._log.emit(
                    "activity.idle", at=at, event=e.type, idle_sec=e.idle_sec, source="agent",
                    **ctx, **skew,
                )
            else:
                self._log.emit(
                    "activity.window", at=at, event=e.type, pid=e.pid, exe=e.exe, title=e.title,
                    source="agent", **ctx, **skew,
                )

    def closed(self, slot: AgentSlot, display_id: int) -> None:
        """The user closed the notice window before acknowledging: log it, show it again soon.

        Ignored unless it is the session's open display and the one this slot was sent."""
        display = self._displays.pending_for_session(slot.session_id)
        if display is None or display.id != display_id or slot.notice_display != display_id:
            return
        self._displays.unacknowledged(display_id, "window_closed")
        slot.notice_display = None
        asyncio.get_running_loop().call_later(
            self.reshow_delay_sec, self.show_pending, slot.session_id
        )

    def agent_exited(self, session_id: int) -> None:
        """The session's agent ended (supervisor, Task 13): its open display went unconfirmed."""
        display = self._displays.pending_for_session(session_id)
        if display is not None:
            self._displays.unacknowledged(display.id, "agent_exited")
        slot = self._slots.get(session_id)
        if slot is not None:
            slot.notice_display = None

    # --- display listener ------------------------------------------------------------------

    def on_display(self, event: DisplayEvent, display: Display) -> None:
        if event == "created":
            self.show_pending(display.session_id)
        elif event == "acknowledged":
            slot = self._slots.get(display.session_id)
            if slot is None:
                return
            self._drop(
                slot, lambda c: c["type"] == "show_notice" and c["display_id"] == display.id
            )
            slot.notice_display = None
            self.queue(display.session_id, {"type": "close_notice", "display_id": display.id})
