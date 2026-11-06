"""Windows event log: the event XML parser and a pull-mode subscription source over pywin32.

``PywinEventLogSource`` and its subscriptions block: use them only from a collector thread (or
``asyncio.to_thread``), never on the event loop.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Protocol
from xml.sax.saxutils import quoteattr

from app.win import IS_WINDOWS

if IS_WINDOWS:
    import pywintypes
    import win32event
    import win32evtlog

EVENT_NS = "http://schemas.microsoft.com/win/2004/08/events/event"
_NS = f"{{{EVENT_NS}}}"
_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z$")

ERROR_ACCESS_DENIED = 5
ERROR_EVT_CHANNEL_NOT_FOUND = 15007
_ERROR_NO_MORE_ITEMS = 259
_ERROR_TIMEOUT = 1460
_ERROR_INVALID_OPERATION = 4317
"""``EvtNext`` again after it ran dry, before the signal fired: nothing to read yet."""
_WAIT_OBJECT_0 = 0
_BATCH = 64
_MAX_BATCHES_PER_NEXT = 16


@dataclass(frozen=True)
class EventRecord:
    channel: str
    provider: str
    event_id: int
    record_id: int
    time_created: datetime
    pid: int | None
    tid: int | None
    user_sid: str | None
    computer: str | None
    data: Mapping[str, str | None]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _int_attr(el: ET.Element | None, name: str) -> int | None:
    if el is None:
        return None
    value = el.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_time(value: str | None) -> datetime:
    """``2026-11-04T05:03:22.4181234Z`` → aware UTC; the fraction is cut to microseconds."""
    m = _TIME.match(value or "")
    if m is None:
        raise ValueError(f"bad TimeCreated {value!r}")
    base = datetime.fromisoformat(m.group(1)).replace(tzinfo=UTC)
    fraction = (m.group(2) or "")[:6].ljust(6, "0")
    return base.replace(microsecond=int(fraction))


def _required_text(system: ET.Element, name: str) -> str:
    el = system.find(_NS + name)
    text = None if el is None else (el.text or "").strip()
    if not text:
        raise ValueError(f"event without {name}")
    return text


def _required_int(system: ET.Element, name: str) -> int:
    text = _required_text(system, name)
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"bad {name} {text!r}") from None


def _event_data(root: ET.Element) -> dict[str, str | None]:
    data: dict[str, str | None] = {}
    event_data = root.find(_NS + "EventData")
    if event_data is not None:
        unnamed = 0
        for el in event_data.findall(_NS + "Data"):
            name = el.get("Name")
            if name is None:
                name = f"Data{unnamed}"
                unnamed += 1
            data[name] = el.text or None
    user_data = root.find(_NS + "UserData")
    if user_data is not None:
        first = next(iter(user_data), None)
        if first is not None:
            for el in first:
                data[_local(el.tag)] = el.text or None
    return data


def parse_event_xml(xml: str) -> EventRecord:
    """One ``EvtRenderEventXml`` event → ``EventRecord``. ``ValueError`` when the XML is broken or
    a required ``System`` part (provider, id, record id, time, channel) is missing."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"malformed event XML: {exc}") from None
    if root.tag != _NS + "Event":
        raise ValueError(f"not an event: {root.tag}")
    system = root.find(_NS + "System")
    if system is None:
        raise ValueError("event without System")
    provider_el = system.find(_NS + "Provider")
    provider = None if provider_el is None else provider_el.get("Name")
    if not provider:
        raise ValueError("event without Provider")
    time_el = system.find(_NS + "TimeCreated")
    execution = system.find(_NS + "Execution")
    security = system.find(_NS + "Security")
    computer = system.find(_NS + "Computer")
    return EventRecord(
        channel=_required_text(system, "Channel"),
        provider=provider,
        event_id=_required_int(system, "EventID"),
        record_id=_required_int(system, "EventRecordID"),
        time_created=_parse_time(None if time_el is None else time_el.get("SystemTime")),
        pid=_int_attr(execution, "ProcessID"),
        tid=_int_attr(execution, "ThreadID"),
        user_sid=None if security is None else security.get("UserID"),
        computer=None if computer is None else (computer.text or None),
        data=MappingProxyType(_event_data(root)),
    )


class EventLogError(Exception):
    """A Windows event log call failed. ``access_denied`` = winerror 5 (e.g. ``Security`` without
    admin rights), ``channel_missing`` = winerror 15007 (e.g. no ``PowerShellCore/Operational``)."""

    def __init__(
        self,
        message: str,
        *,
        access_denied: bool = False,
        channel_missing: bool = False,
        winerror: int | None = None,
    ) -> None:
        super().__init__(message)
        self.access_denied = access_denied
        self.channel_missing = channel_missing
        self.winerror = winerror


class EventSubscription(Protocol):
    def next(self, timeout_ms: int) -> list[str]:
        """Event XML strings; ``[]`` when nothing arrived within ``timeout_ms``."""
        ...

    def close(self) -> None: ...


class EventLogSource(Protocol):
    def open(self, channel: str, xpath: str, after_record_id: int | None) -> EventSubscription:
        """Subscribe from just after ``after_record_id``, or to future events when ``None``."""
        ...

    def latest_record_id(self, channel: str) -> int | None: ...


def _wrap(exc: Any) -> EventLogError:
    code = getattr(exc, "winerror", None)
    message = f"{getattr(exc, 'funcname', '') or 'event log'}: {getattr(exc, 'strerror', exc)} ({code})"
    return EventLogError(
        message,
        access_denied=code == ERROR_ACCESS_DENIED,
        channel_missing=code == ERROR_EVT_CHANNEL_NOT_FOUND,
        winerror=code,
    )


def bookmark_xml(channel: str, record_id: int) -> str:
    return (
        f"<BookmarkList><Bookmark Channel={quoteattr(channel)} "
        f"RecordId='{record_id}' IsCurrent='true'/></BookmarkList>"
    )


class _PywinSubscription:
    """``EvtSubscribe`` pull mode. ``EvtNext`` is called until it runs dry; after that it is only
    called again once the signal fires (calling it earlier fails with ``ERROR_INVALID_OPERATION``).
    A new subscription starts "maybe ready": events already in the log after the bookmark do not
    set the signal."""

    def __init__(self, handle: Any, signal: Any) -> None:
        self._handle = handle
        self._signal = signal
        self._ready = True
        self._closed = False

    def next(self, timeout_ms: int) -> list[str]:
        if self._closed:
            return []
        try:
            if not self._ready:
                if win32event.WaitForSingleObject(self._signal, timeout_ms) != _WAIT_OBJECT_0:
                    return []
                self._ready = True
            out: list[str] = []
            for _ in range(_MAX_BATCHES_PER_NEXT):
                events = self._evt_next()
                if not events:
                    self._ready = False
                    break
                out.extend(win32evtlog.EvtRender(e, win32evtlog.EvtRenderEventXml) for e in events)
            return out
        except pywintypes.error as exc:
            raise _wrap(exc) from exc

    def _evt_next(self) -> tuple[Any, ...]:
        try:
            return tuple(win32evtlog.EvtNext(self._handle, _BATCH, 0))
        except pywintypes.error as exc:
            if exc.winerror in (_ERROR_NO_MORE_ITEMS, _ERROR_TIMEOUT, _ERROR_INVALID_OPERATION):
                return ()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for handle in (self._handle, self._signal):
            try:
                handle.Close()
            except Exception:  # already closed or invalid: nothing left to release
                pass


class PywinEventLogSource:
    """The real event log through ``win32evtlog`` (pywin32)."""

    def open(self, channel: str, xpath: str, after_record_id: int | None) -> EventSubscription:
        signal = None
        try:
            signal = win32event.CreateEvent(None, 0, 0, None)
            if after_record_id is None:
                handle = win32evtlog.EvtSubscribe(
                    channel, win32evtlog.EvtSubscribeToFutureEvents,
                    SignalEvent=signal, Query=xpath,
                )
            else:
                bookmark = win32evtlog.EvtCreateBookmark(bookmark_xml(channel, after_record_id))
                handle = win32evtlog.EvtSubscribe(
                    channel, win32evtlog.EvtSubscribeStartAfterBookmark,
                    SignalEvent=signal, Query=xpath, Bookmark=bookmark,
                )
        except pywintypes.error as exc:
            if signal is not None:
                signal.Close()
            raise _wrap(exc) from exc
        return _PywinSubscription(handle, signal)

    def latest_record_id(self, channel: str) -> int | None:
        try:
            query = win32evtlog.EvtQuery(
                channel,
                win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryReverseDirection,
                "*",
            )
            try:
                events = win32evtlog.EvtNext(query, 1)
            except pywintypes.error as exc:
                if exc.winerror == _ERROR_NO_MORE_ITEMS:
                    return None
                raise
            if not events:
                return None
            xml = win32evtlog.EvtRender(events[0], win32evtlog.EvtRenderEventXml)
        except pywintypes.error as exc:
            raise _wrap(exc) from exc
        return parse_event_xml(xml).record_id
