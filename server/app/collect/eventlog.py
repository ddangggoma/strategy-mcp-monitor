"""Event log collection: one watcher thread per channel, JSON bookmarks, per-channel health.

A ``ChannelWatcher`` thread reads one channel and only calls its two ``post`` functions (bridge
posts); handlers registered with ``EventLogComponent.on`` run later on the loop thread. Bookmarks
live in ``data/collector-state.json`` (V12), never in ``config.db``: a collector thread must not
touch the database.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

from app.clock import Clock
from app.collect.bridge import CollectorBridge
from app.collect.manager import Collectors
from app.win.eventlog import EventLogSource, EventRecord, EventSubscription, parse_event_xml

StatusItem = tuple[str, bool, str | None]
"""``(spec name, ok, error)`` as posted to the ``"eventlog:status"`` bridge source."""

STATUS_SOURCE = "eventlog:status"


@dataclass(frozen=True)
class ChannelSpec:
    name: str
    """The bridge source and collector-status name, e.g. ``eventlog:lsm``."""
    channel: str
    event_ids: tuple[int, ...]


CHANNELS: tuple[ChannelSpec, ...] = (
    ChannelSpec(
        "eventlog:security", "Security",
        (1102, 4624, 4625, 4634, 4647, 4688, 4719, 4778, 4779, 4800, 4801),
    ),
    ChannelSpec(
        "eventlog:lsm", "Microsoft-Windows-TerminalServices-LocalSessionManager/Operational",
        (21, 22, 23, 24, 25),
    ),
    ChannelSpec(
        "eventlog:rcm", "Microsoft-Windows-TerminalServices-RemoteConnectionManager/Operational",
        (1149,),
    ),
    ChannelSpec("eventlog:powershell", "Microsoft-Windows-PowerShell/Operational", (4104,)),
    ChannelSpec("eventlog:pwsh", "PowerShellCore/Operational", (4104,)),
    ChannelSpec("eventlog:system", "System", (104,)),
)


def xpath_for(ids: Iterable[int]) -> str:
    """``[21, 25]`` → ``*[System[(EventID=21 or EventID=25)]]``."""
    terms = [f"EventID={int(i)}" for i in ids]
    if not terms:
        raise ValueError("an event log query needs at least one event id")
    return f"*[System[({' or '.join(terms)})]]"


class BookmarkStore:
    """``{channel: last record id}`` in a JSON file, replaced atomically on every ``set``.

    A missing file is an empty store; an unreadable or wrongly shaped one is also empty, with one
    line on stderr. Thread-safe (every channel watcher shares one store)."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._marks: dict[str, int] = self._load()

    def _load(self) -> dict[str, int]:
        try:
            raw = self._path.read_text("utf-8")
        except FileNotFoundError:
            return {}
        except OSError:
            raw = ""
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if not isinstance(data, dict) or not all(
            isinstance(k, str) and type(v) is int for k, v in data.items()
        ):
            print("collector-state: corrupt bookmark file, starting fresh",
                  file=sys.stderr, flush=True)
            return {}
        return dict(data)

    def get(self, channel: str) -> int | None:
        with self._lock:
            return self._marks.get(channel)

    def set(self, channel: str, record_id: int) -> None:
        with self._lock:
            self._marks[channel] = record_id
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._marks, sort_keys=True), "utf-8")
            os.replace(tmp, self._path)


class ChannelWatcher:
    """Reads one channel on its own thread and posts parsed records and health changes.

    It starts after the stored bookmark, else after the newest record now in the log (a first run
    does not replay history). Unparsable events are skipped and counted, events older than
    ``max_age`` are dropped (both still move the bookmark). The last record id is saved every
    ``save_every_sec`` and on stop. Any failure posts ``(name, False, str(exc))``, waits
    ``retry_sec`` (interruptible by ``stop``) and opens again after the last record seen."""

    def __init__(
        self,
        spec: ChannelSpec,
        source: EventLogSource,
        post_record: Callable[[EventRecord], None],
        post_status: Callable[[StatusItem], None],
        bookmarks: BookmarkStore,
        *,
        now: Callable[[], datetime],
        retry_sec: float = 60,
        save_every_sec: float = 5,
        max_age: timedelta = timedelta(hours=24),
    ) -> None:
        self.spec = spec
        self._source = source
        self._post_record = post_record
        self._post_status = post_status
        self._bookmarks = bookmarks
        self._now = now
        self._retry_sec = retry_sec
        self._save_every_sec = save_every_sec
        self._max_age = max_age
        self._xpath = xpath_for(spec.event_ids)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: int | None = None
        self._saved: int | None = None
        self.parse_errors = 0

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("watcher already started")
        self._thread = threading.Thread(target=self._run, name=self.spec.name, daemon=True)
        self._thread.start()

    def request_stop(self) -> None:
        self._stop.set()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def too_old(self, record: EventRecord) -> bool:
        return record.time_created < self._now() - self._max_age

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._watch()
            except Exception as exc:
                self._post_status((self.spec.name, False, str(exc) or repr(exc)))
                self._stop.wait(self._retry_sec)

    def _start_after(self) -> int | None:
        if self._last is not None:
            return self._last
        after = self._bookmarks.get(self.spec.channel)
        if after is None:
            after = self._source.latest_record_id(self.spec.channel)
        self._last = after
        return after

    def _watch(self) -> None:
        sub: EventSubscription = self._source.open(
            self.spec.channel, self._xpath, self._start_after()
        )
        try:
            self._post_status((self.spec.name, True, None))
            saved_at = time.monotonic()
            while not self._stop.is_set():
                for xml in sub.next(500):
                    self._handle(xml)
                if time.monotonic() - saved_at >= self._save_every_sec:
                    self._save()
                    saved_at = time.monotonic()
        finally:
            try:
                sub.close()
            finally:
                self._save()

    def _handle(self, xml: str) -> None:
        try:
            record = parse_event_xml(xml)
        except ValueError:
            self.parse_errors += 1
            return
        self._last = record.record_id
        if self.too_old(record):
            return
        self._post_record(record)

    def _save(self) -> None:
        last = self._last
        if last is None or last == self._saved:
            return
        try:
            self._bookmarks.set(self.spec.channel, last)
        except OSError:  # e.g. the file is briefly locked; the next save tries again
            return
        self._saved = last


class EventLogComponent:
    """Opens a ``ChannelWatcher`` for every channel that has at least one handler.

    Handlers (``on``) must be registered before ``start``; each channel's records reach its
    handlers on the loop thread, in registration order, one handler failing does not stop the
    next. Channel health goes to ``Collectors.report`` under the spec name."""

    name = "eventlog"

    def __init__(
        self,
        source: EventLogSource,
        bookmarks: BookmarkStore,
        collectors: Collectors,
        clock: Clock,
        specs: tuple[ChannelSpec, ...] = CHANNELS,
    ) -> None:
        self._source = source
        self._bookmarks = bookmarks
        self._collectors = collectors
        self._clock = clock
        self._specs = specs
        self._handlers: dict[str, list[Callable[[list[EventRecord]], None]]] = {
            spec.name: [] for spec in specs
        }
        self._watchers: list[ChannelWatcher] = []
        self._started = False

    def on(self, spec_name: str, handler: Callable[[list[EventRecord]], None]) -> None:
        if spec_name not in self._handlers:
            raise ValueError(f"unknown event log channel {spec_name!r}")
        if self._started:
            raise RuntimeError("event log handlers must be registered before start()")
        self._handlers[spec_name].append(handler)

    def start(self, bridge: CollectorBridge) -> None:
        self._started = True
        specs = [spec for spec in self._specs if self._handlers[spec.name]]
        if not specs:
            return
        post_status = bridge.register(STATUS_SOURCE, self._on_status)
        for spec in specs:
            post_record = bridge.register(spec.name, partial(self._dispatch, spec.name))
            self._watchers.append(ChannelWatcher(
                spec, self._source, post_record, post_status, self._bookmarks,
                now=self._clock.now,
            ))
        for watcher in self._watchers:
            watcher.start()

    def stop(self) -> None:
        for watcher in self._watchers:
            watcher.request_stop()
        for watcher in self._watchers:
            watcher.stop()

    def _on_status(self, items: list[StatusItem]) -> None:
        for name, ok, error in items:
            self._collectors.report(name, ok, error)

    def _dispatch(self, spec_name: str, records: list[EventRecord]) -> None:
        for handler in self._handlers[spec_name]:
            try:
                handler(records)
            except Exception as exc:
                self._collectors.handler_failed(spec_name, exc)
