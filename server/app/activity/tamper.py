"""Bypass (tamper) detection hub (V19): every detector reports here, so each event is written to the
``tamper`` log, kept in a small in-memory ring for ``GET /api/tamper/recent`` and pushed to logged-in
board subscribers as the SSE ``tamper`` event (never to anonymous ones).

Also here: the event log detectors (audit policy changed, log cleared) and the 60-second
``TamperScanner`` (audit registry drift, MCP script files, daily log files)."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import itertools
import json
import os
import re
import sys
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from app.clock import Clock, to_kst_iso
from app.logstore.writer import LogSink
from app.monitor.bus import BoardBus
from app.win import IS_WINDOWS
from app.win.eventlog import EventRecord

if IS_WINDOWS:
    import winreg

if TYPE_CHECKING:
    from app.collect.manager import Collectors
    from app.monitor.scripts import ScriptStore
    from app.monitor.store import McpStore


_THROTTLE_KEYS_MAX = 1024
MISUSE_REPORT_SEC = 60.0
"""``agent_impersonation`` / ``notice_token_misuse`` are reported once per key per minute (M3)."""


class TamperMonitor:
    """Loop thread only (collector threads go through the ``CollectorBridge``)."""

    def __init__(self, log: LogSink, bus: BoardBus, clock: Clock, *, keep: int = 200) -> None:
        self._log = log
        self._bus = bus
        self._clock = clock
        self._ring: deque[dict[str, Any]] = deque(maxlen=keep)
        self._throttle: dict[tuple[Any, ...], tuple[datetime, int]] = {}

    def report_throttled(
        self, event: str, *, key: tuple[Any, ...], window_sec: float = 60.0, **fields: Any
    ) -> dict[str, Any] | None:
        """``report`` at most once per (``event``, ``key``) per ``window_sec`` (M3): a token replayed
        in a loop must not flood the log, the ring or the SSE stream. The next report after the
        window carries ``suppressed`` = how many were swallowed since the last one. None when this
        one was swallowed."""
        now = self._clock.now()
        full = (event, *key)
        last = self._throttle.get(full)
        if last is not None and (now - last[0]).total_seconds() < window_sec:
            self._throttle[full] = (last[0], last[1] + 1)
            return None
        if len(self._throttle) >= _THROTTLE_KEYS_MAX:
            self._throttle = {
                k: v for k, v in self._throttle.items()
                if (now - v[0]).total_seconds() < window_sec
            }
            while len(self._throttle) >= _THROTTLE_KEYS_MAX:
                del self._throttle[next(iter(self._throttle))]
        self._throttle.pop(full, None)
        self._throttle[full] = (now, 0)
        extra: dict[str, Any] = {"suppressed": last[1]} if last is not None and last[1] else {}
        return self.report(event, **fields, **extra)

    def report(self, event: str, *, at: datetime | None = None, **fields: Any) -> dict[str, Any]:
        """Record one tamper event; ``at`` is the event time (default: now). Returns the record."""
        record: dict[str, Any] = {"at": to_kst_iso(at or self._clock.now()), "event": event, **fields}
        self._log.emit("tamper", at=at, event=event, **fields)
        self._ring.append(record)
        self._bus.publish("tamper", record, public=False)
        return record

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """The newest ``limit`` records, newest first."""
        return [dict(r) for r in itertools.islice(reversed(self._ring), limit)]


# ---- event log: audit policy changed (Security 4719), log cleared (Security 1102, System 104) ----

_EVENTLOG_PROVIDER = "Microsoft-Windows-Eventlog"


def _subject(r: EventRecord) -> str | None:
    """``SubjectDomainName\\SubjectUserName``, or just the name when there is no domain."""
    name = r.data.get("SubjectUserName")
    if not name:
        return None
    domain = r.data.get("SubjectDomainName")
    return f"{domain}\\{name}" if domain else name


def map_tamper_record(r: EventRecord) -> tuple[str, dict[str, Any]] | None:
    """A Security/System event → ``(tamper event, fields)``; ``None`` for every other event."""
    if r.channel == "Security" and r.event_id == 4719:
        return "audit_policy_changed", {
            "user": _subject(r),
            "category": r.data.get("CategoryId"),
            "subcategory": r.data.get("SubcategoryGuid"),
            "changes": r.data.get("AuditPolicyChanges"),
        }
    if r.channel == "Security" and r.event_id == 1102 and r.provider == _EVENTLOG_PROVIDER:
        return "log_cleared", {"channel": "Security", "user": _subject(r)}
    if r.channel == "System" and r.event_id == 104 and r.provider == _EVENTLOG_PROVIDER:
        return "log_cleared", {"channel": r.data.get("Channel"), "user": _subject(r)}
    return None


class TamperEventHandler:
    """Event log handler (``eventlog:security``, ``eventlog:system``); loop thread."""

    def __init__(self, tamper: TamperMonitor) -> None:
        self._tamper = tamper

    def __call__(self, records: list[EventRecord]) -> None:
        for r in records:
            mapped = map_tamper_record(r)
            if mapped is None:
                continue
            name, fields = mapped
            self._tamper.report(
                name, at=r.time_created, source=f"eventlog:{r.event_id}", record_id=r.record_id,
                **fields,
            )


# ---- the 60-second scan: audit registry, script files, log files ----

@dataclass(frozen=True)
class RegistryValue:
    path: str
    """Key path under ``HKEY_LOCAL_MACHINE``."""
    name: str

    @property
    def key(self) -> str:
        """``<path>\\<name>``: how the value is named in ``audit.config`` and ``audit_config_changed``."""
        return f"{self.path}\\{self.name}"


AUDIT_REGISTRY: tuple[RegistryValue, ...] = (
    RegistryValue(
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit",
        "ProcessCreationIncludeCmdLine_Enabled",
    ),
    RegistryValue(
        r"SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging",
        "EnableScriptBlockLogging",
    ),
)


def read_hklm(v: RegistryValue) -> int | str | None:
    """One ``HKEY_LOCAL_MACHINE`` value (read-only); ``None`` when the key or value is missing (or
    off Windows). Other ``OSError``s (e.g. access denied) propagate."""
    if not IS_WINDOWS:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, v.path) as key:
            value, _type = winreg.QueryValueEx(key, v.name)
    except FileNotFoundError:
        return None
    if value is None or isinstance(value, int | str):
        return value
    return str(value)


_LOG_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.jsonl(\.gz)?$", re.ASCII)
_MISSING = "missing"
"""What ``TamperScanner`` remembers as reported for a script file that is gone."""


def _str_map(value: Any, types: tuple[type, ...]) -> dict[str, Any] | None:
    """A saved ``{str: value}`` map (``None`` = never scanned); ``ValueError`` for any other shape.
    ``bool`` is rejected where ``int`` is expected (JSON ``true`` is not a size)."""
    if value is None:
        return None
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and type(v) in types for k, v in value.items()
    ):
        raise ValueError("bad map")
    return dict(value)


class Scannable(Protocol):
    def scan(self) -> None: ...


class TamperScanner:
    """Compares the audit registry, the MCP script files and the daily log files with what it saw
    last time (``scan()`` every 60 s, loop thread; the files are small enough to read inline).

    - Registry: the first scan only logs ``system`` ``audit.config`` with every value; afterwards a
      changed value reports ``audit_config_changed`` once. A value that cannot be read is ``None``.
    - Scripts: a file that is gone (``script_file_missing``) or whose sha256 differs from the DB
      (``script_file_changed``) is reported once per ``(mcp_id, kind, actual)`` until it matches.
    - Logs: a ``YYYY-MM-DD.jsonl[.gz]`` file that disappeared (``log_file_removed``, unless
      announced by ``expect_log_removed``) or shrank (``log_file_truncated``). Growth is normal.

    With ``baseline_path`` (the service: ``data/tamper-baseline.json``, preflight F07) the state
    survives a restart: it is saved after every scan and every announced removal, and the first
    scan of the next run compares the registry and the log files with the saved state, so a change
    made while the service was stopped is reported (``while_stopped: true``). Script files are
    always compared with the DB; the saved "already reported" set keeps an unfixed change from
    being reported again at every start.
    """

    def __init__(
        self,
        tamper: TamperMonitor,
        scripts: ScriptStore,
        mcps: McpStore,
        logs_dir: Path,
        log: LogSink,
        *,
        read_value: Callable[[RegistryValue], int | str | None] = read_hklm,
        registry: tuple[RegistryValue, ...] = AUDIT_REGISTRY,
        baseline_path: Path | None = None,
    ) -> None:
        self._tamper = tamper
        self._scripts = scripts
        self._mcps = mcps
        self._logs_dir = logs_dir
        self._log = log
        self._read_value = read_value
        self._registry = registry
        self._values: dict[str, int | str | None] | None = None
        self._script_reported: dict[tuple[int, str], str] = {}
        """``(mcp_id, kind)`` → the reported actual sha256, or ``_MISSING``."""
        self._log_sizes: dict[str, int] | None = None
        self._expected_removals: set[str] = set()
        self._baseline_path = baseline_path
        self._saved_text: str | None = None
        self._save_failing = False
        # The previous run's last state, compared by this run's first scan (then dropped).
        self._prev_values: dict[str, int | str | None] | None = None
        self._prev_log_sizes: dict[str, int] | None = None
        # Why the persisted baseline could not be used ("corrupt", or "missing" while logs already
        # exist): reported by the first scan instead of starting fresh silently (plan review minor 7).
        self._baseline_reset: str | None = None
        if baseline_path is not None:
            self._load_baseline(baseline_path)

    def expect_log_removed(self, file_name: str) -> None:
        """Announce that ``file_name`` is about to be deleted on purpose (retention, Plan 5): its
        disappearance is forgotten quietly instead of reported (also after a restart)."""
        self._expected_removals.add(file_name)
        self._save_baseline()

    def cancel_log_removal(self, file_name: str) -> None:
        """The announced deletion of ``file_name`` failed: a later disappearance is reported again."""
        if file_name in self._expected_removals:
            self._expected_removals.discard(file_name)
            self._save_baseline()

    def scan(self) -> None:
        if self._baseline_reset is not None:
            # someone with admin rights could stop the service and delete the baseline with the logs:
            # what changed while stopped can no longer be compared, so that itself is the finding
            self._tamper.report("baseline_reset", reason=self._baseline_reset, while_stopped=True)
            self._baseline_reset = None
        self._scan_registry()
        self._scan_scripts()
        self._scan_logs()
        self._save_baseline()

    # -- the persisted baseline (F07) ------------------------------------------------------------

    def _load_baseline(self, path: Path) -> None:
        try:
            raw = path.read_text("utf-8")
        except FileNotFoundError:
            if self._list_logs():  # logs from an earlier run, but no baseline: removed, not new
                self._baseline_reset = "missing"
            return
        except OSError:
            raw = ""
        try:
            data = json.loads(raw)
            registry = _str_map(data["registry"], (int, str, type(None)))
            logs = _str_map(data["logs"], (int,))
            reported = {}
            for mcp_id, kind, actual in data["scripts"]:
                if type(mcp_id) is not int or not isinstance(kind, str) or not isinstance(actual, str):
                    raise ValueError("bad script entry")
                reported[(mcp_id, kind)] = actual
            removals = data["expected_removals"]
            if not isinstance(removals, list) or not all(isinstance(n, str) for n in removals):
                raise ValueError("bad expected_removals")
        except (ValueError, TypeError, KeyError):
            print("tamper-baseline: corrupt file, starting fresh", file=sys.stderr, flush=True)
            self._baseline_reset = "corrupt"
            return
        self._prev_values = registry
        self._prev_log_sizes = logs
        self._script_reported = reported
        self._expected_removals = set(removals)

    def _save_baseline(self) -> None:
        """Write the state atomically when it changed; a failure is logged once (until a save
        works again) and never raised: a scan or a retention delete must not fail on it."""
        path = self._baseline_path
        if path is None:
            return
        state = {
            "version": 1,
            "registry": self._values if self._values is not None else self._prev_values,
            "logs": self._log_sizes if self._log_sizes is not None else self._prev_log_sizes,
            "scripts": sorted([mcp_id, kind, actual] for (mcp_id, kind), actual in self._script_reported.items()),
            "expected_removals": sorted(self._expected_removals),
        }
        text = json.dumps(state, sort_keys=True, ensure_ascii=False)
        if text == self._saved_text:
            return
        tmp = path.with_name(path.name + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(text, "utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
            if not self._save_failing:
                self._save_failing = True
                self._log.emit("system", event="tamper.baseline_save_failed", path=str(path), error=repr(exc))
            return
        self._saved_text = text
        self._save_failing = False

    # -- the scans -------------------------------------------------------------------------------

    def _read(self, v: RegistryValue) -> int | str | None:
        try:
            return self._read_value(v)
        except OSError:
            return None

    def _scan_registry(self) -> None:
        values = {v.key: self._read(v) for v in self._registry}
        before, self._values = self._values, values
        if before is None:
            self._log.emit("system", event="audit.config", values=values)
            prev, self._prev_values = self._prev_values, None
            for key, value in values.items():  # changed while the service was stopped
                if prev is not None and key in prev and prev[key] != value:
                    self._tamper.report(
                        "audit_config_changed", key=key, before=prev[key], after=value, while_stopped=True
                    )
            return
        for key, value in values.items():
            if before.get(key) != value:
                self._tamper.report("audit_config_changed", key=key, before=before.get(key), after=value)

    def _scan_scripts(self) -> None:
        seen: set[tuple[int, str]] = set()
        for mcp in self._mcps.list():
            for info in self._scripts.list(mcp.id):
                slot = (mcp.id, info.kind)
                seen.add(slot)
                try:
                    data = info.path.read_bytes()
                except FileNotFoundError:
                    actual = _MISSING
                except OSError:  # e.g. a sharing violation: try again next scan
                    continue
                else:
                    actual = hashlib.sha256(data).hexdigest()
                if actual == info.sha256:
                    self._script_reported.pop(slot, None)
                    continue
                if self._script_reported.get(slot) == actual:
                    continue
                self._script_reported[slot] = actual
                fields: dict[str, Any] = {"mcp_id": mcp.id, "kind": info.kind, "path": str(info.path)}
                if actual == _MISSING:
                    self._tamper.report("script_file_missing", **fields)
                else:
                    self._tamper.report(
                        "script_file_changed", **fields,
                        expected_sha256=info.sha256, actual_sha256=actual,
                    )
        for slot in set(self._script_reported) - seen:  # MCP or script deleted
            del self._script_reported[slot]

    def _list_logs(self) -> dict[str, int] | None:
        """``{file name: size}``; ``None`` when the directory cannot be read (skip this scan)."""
        try:
            entries = list(self._logs_dir.iterdir())
        except FileNotFoundError:
            return {}
        except OSError:
            return None
        sizes: dict[str, int] = {}
        for entry in entries:
            if _LOG_FILE.match(entry.name) is None:
                continue
            try:
                if entry.is_file():
                    sizes[entry.name] = entry.stat().st_size
            except OSError:  # deleted between listing and stat: treated as gone
                continue
        return sizes

    def _scan_logs(self) -> None:
        sizes = self._list_logs()
        if sizes is None:
            return
        before, self._log_sizes = self._log_sizes, sizes
        extra: dict[str, Any] = {}
        if before is None and self._prev_log_sizes is not None:  # first scan after a restart
            before, self._prev_log_sizes = self._prev_log_sizes, None
            extra = {"while_stopped": True}
        if before is not None:
            for name, size in sorted(before.items()):
                after = sizes.get(name)
                if after is None:
                    if name in self._expected_removals:
                        continue
                    self._tamper.report("log_file_removed", file=name, **extra)
                elif after < size:
                    self._tamper.report("log_file_truncated", file=name, before=size, after=after, **extra)
        self._expected_removals &= set(sizes)  # announced files that are gone need no more notice


async def scan_every(
    scanner: Scannable, collectors: Collectors, *, interval_sec: float = 60.0
) -> None:
    """The ``tamper-scan`` collector task: a first scan at once (the baselines), then one every
    ``interval_sec``; a failing scan is logged (``collector.handler_failed``) and the loop goes on."""
    while True:
        try:
            scanner.scan()
        except Exception as exc:
            collectors.handler_failed("tamper-scan", exc)
        await asyncio.sleep(interval_sec)
