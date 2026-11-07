"""Debounce raw WinEvents into what the monitor logs as ``activity.window`` lines.

Alt-Tab bursts keep only the last foreground window, a busy window's title changes merge into its
last title, and repeats of what was already sent are dropped. Times ``t`` are monotonic seconds.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Kind = Literal["foreground", "minimize", "restore", "title"]

_TITLE_MEMORY = 256  # windows whose last sent title is remembered


@dataclass(frozen=True)
class RawWinEvent:
    t: float
    kind: Kind
    hwnd: int
    pid: int
    exe: str | None
    title: str
    at: datetime


class WindowEventCoalescer:
    """Not thread-safe: the caller (``EventPump``) holds a lock around ``add`` and ``drain``."""

    def __init__(self, *, fg_merge_sec: float = 0.3, title_merge_sec: float = 1.0, dup_sec: float = 0.3) -> None:
        self._fg_merge = fg_merge_sec
        self._title_merge = title_merge_sec
        self._dup = dup_sec
        self._foregrounds: list[RawWinEvent] = []
        self._titles: dict[int, RawWinEvent] = {}
        self._others: list[RawWinEvent] = []
        self._seen: dict[tuple[int, str], float] = {}  # (hwnd, minimize|restore) -> last t
        self._current: int | None = None  # the foreground window as of the last add
        self._sent_fg: tuple[int, str] | None = None
        self._sent_titles: OrderedDict[int, str] = OrderedDict()

    def add(self, e: RawWinEvent) -> None:
        if e.kind == "foreground":
            if self._foregrounds and e.t - self._foregrounds[-1].t < self._fg_merge:
                self._foregrounds[-1] = e
            else:
                self._foregrounds.append(e)
            self._current = e.hwnd
        elif e.kind == "title":
            if e.hwnd == self._current:
                self._titles[e.hwnd] = e  # replaces a pending title of the same window
        else:
            key = (e.hwnd, e.kind)
            last = self._seen.get(key)
            self._seen[key] = e.t
            if last is None or e.t - last >= self._dup:
                self._others.append(e)

    def drain(self, now: float) -> list[RawWinEvent]:
        ready = [e for e in self._foregrounds if e.t + self._fg_merge <= now]
        self._foregrounds = [e for e in self._foregrounds if e.t + self._fg_merge > now]
        for hwnd, e in list(self._titles.items()):
            if e.t + self._title_merge <= now:
                ready.append(e)
                del self._titles[hwnd]
        ready.extend(self._others)
        self._others = []
        self._seen = {k: t for k, t in self._seen.items() if t + self._dup > now}

        out: list[RawWinEvent] = []
        for e in sorted(ready, key=lambda x: x.t):
            if e.kind == "foreground":
                if self._sent_fg == (e.hwnd, e.title):
                    continue
                self._sent_fg = (e.hwnd, e.title)
                self._remember_title(e.hwnd, e.title)
            elif e.kind == "title":
                if self._sent_titles.get(e.hwnd) == e.title:
                    continue
                self._remember_title(e.hwnd, e.title)
            out.append(e)
        return out

    def _remember_title(self, hwnd: int, title: str) -> None:
        self._sent_titles[hwnd] = title
        self._sent_titles.move_to_end(hwnd)
        while len(self._sent_titles) > _TITLE_MEMORY:
            self._sent_titles.popitem(last=False)
