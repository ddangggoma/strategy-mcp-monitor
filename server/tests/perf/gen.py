"""Synthetic daily JSONL logs for the 1M-row performance harness (ruling W9).

The output depends only on the arguments: change the rules here and bump ``GEN_VERSION`` so the
cached index under ``server/.cache/`` is rebuilt (W39).

``python -m tests.perf.gen`` (from ``server/``) builds the 1M-row cache ahead of the perf run.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

GEN_VERSION = 1

CATEGORY_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("activity.window", 40), ("activity.process", 25), ("activity.command", 10), ("mcp.health", 8),
    ("system", 7), ("session", 3), ("auth", 2), ("activity.idle", 1.5), ("mcp.action", 1),
    ("admin.audit", 1), ("notice", 1), ("tamper", 0.5),
)
WINDOWS_USERS = tuple(f"CORP\\user{k:02d}" for k in range(1, 21))
WEB_USERS = tuple(f"dev{k}@x.com" for k in range(1, 6))
IPS = tuple(f"10.0.3.{i}" for i in range(1, 31))
VOCABULARY_SIZE = 2000
KEYWORD = "zebra"  # in 5% of activity.command bodies as "zebra-<n>": 0.5% of all rows
_DAY_MS = 86_400_000


@dataclass(frozen=True)
class GenInfo:
    rows: int
    days: int
    users: list[str]
    sessions: dict[str, int]  # Windows user → its session id
    end_day: date


def sessions() -> dict[str, int]:
    """User k's session is ``(k % 8) + 2``."""
    return {u: (k % 8) + 2 for k, u in enumerate(WINDOWS_USERS, start=1)}


def vocabulary(rnd: random.Random) -> list[str]:
    """2,000 distinct words, English-like and Korean mixed, none starting with the keyword."""
    words: set[str] = set()
    out: list[str] = []
    while len(out) < VOCABULARY_SIZE:
        if rnd.random() < 0.6:
            w = "".join(rnd.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rnd.randint(3, 9)))
        else:
            w = "".join(chr(rnd.randint(0xAC00, 0xD7A3)) for _ in range(rnd.randint(2, 4)))
        if w not in words and not w.startswith(KEYWORD):
            words.add(w)
            out.append(w)
    return out


def _ts(day: date, ms_of_day: int) -> str:
    s, ms = divmod(ms_of_day, 1000)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{day.isoformat()}T{h:02d}:{m:02d}:{sec:02d}.{ms:03d}+09:00"


class _Events:
    def __init__(self, rnd: random.Random) -> None:
        self.rnd = rnd
        self.words = vocabulary(rnd)
        self.sessions = sessions()
        self.cats = [c for c, _ in CATEGORY_WEIGHTS]
        self.weights = [w for _, w in CATEGORY_WEIGHTS]

    def body(self) -> str:
        return " ".join(self.rnd.choices(self.words, k=self.rnd.randint(4, 12)))

    def event(self, ts: str) -> dict[str, Any]:
        rnd = self.rnd
        cat = rnd.choices(self.cats, self.weights)[0]
        e: dict[str, Any] = {"ts": ts, "cat": cat}
        if cat.startswith("activity.") or cat in ("session", "notice"):
            user = rnd.choice(WINDOWS_USERS)
            sid = self.sessions[user]
            if cat == "activity.window":
                e.update(event="focus", pid=rnd.randint(100, 9999), exe=rnd.choice(("chrome.exe", "code.exe", "excel.exe")),
                         title=self.body(), source="agent")
            elif cat == "activity.process":
                e.update(event=rnd.choice(("start", "stop")), name="tool.exe", pid=rnd.randint(100, 9999),
                         ppid=rnd.randint(100, 9999), cmdline=self.body())
            elif cat == "activity.command":
                text = self.body()
                if rnd.random() < 0.05:
                    text += f" {KEYWORD}-{rnd.randint(1, 999)}"
                e.update(event="script_block", shell="powershell", text=text, pid=rnd.randint(100, 9999))
            elif cat == "activity.idle":
                e.update(event=rnd.choice(("idle", "active")), idle_sec=rnd.randint(60, 900), source="agent",
                         detail=self.body())
            elif cat == "session":
                e.update(event=rnd.choice(("connect", "disconnect", "logon", "logoff")), client_ip=rnd.choice(IPS),
                         client_name=self.body(), source="wts")
            else:  # notice
                e.update(event="notice_acknowledged", version=4, attempt=1, text=self.body())
            e.update(session_id=sid, user=user)
        elif cat == "auth":
            e.update(event="login", email=rnd.choice(WEB_USERS), channel=rnd.choice(("local", "external")),
                     ip=rnd.choice(IPS), user_agent=self.body(), ok=rnd.random() < 0.9)
        elif cat == "admin.audit":
            e.update(actor_id=rnd.randint(1, 5), actor_email=rnd.choice(WEB_USERS),
                     action=rnd.choice(("settings_update", "mcp_update", "user_invite")),
                     channel=rnd.choice(("local", "external")), ip=rnd.choice(IPS),
                     target={"note": self.body()}, result="ok")
        elif cat == "mcp.action":
            e.update(mcp_id=rnd.randint(1, 8), name=rnd.choice(self.words), run_id=f"r{rnd.randint(1, 10**6)}",
                     kind="restart", trigger="manual", actor=rnd.choice(WEB_USERS),
                     status=rnd.choice(("ok", "failed")), stdout=self.body())
        elif cat == "mcp.health":
            e.update(mcp_id=rnd.randint(1, 8), name=rnd.choice(self.words), **{"from": "UP", "to": "DOWN"},
                     issue=self.body())
        elif cat == "tamper":
            e.update(event="audit_config_changed", key=rnd.choice(self.words), before=1, after=0, note=self.body())
        else:  # system
            e.update(event=rnd.choice(("collector.status", "audit.config")), source="wmi", ok=True, message=self.body())
        return e


def generate(logs_dir: Path, rows: int, days: int, end_day: date, seed: int) -> GenInfo:
    """Write ``rows`` events over the ``days`` days ending ``end_day`` (KST), one ``YYYY-MM-DD.jsonl``
    per day, in time order."""
    rnd = random.Random(seed)
    events = _Events(rnd)
    logs_dir.mkdir(parents=True, exist_ok=True)
    for i in range(days):
        day = end_day - timedelta(days=days - 1 - i)
        n = rows // days + (1 if i < rows % days else 0)
        stamps = sorted(rnd.randrange(_DAY_MS) for _ in range(n))
        lines = [json.dumps(events.event(_ts(day, t)), ensure_ascii=False) for t in stamps]
        (logs_dir / f"{day.isoformat()}.jsonl").write_text("".join(ln + "\n" for ln in lines), encoding="utf-8")
    return GenInfo(rows=rows, days=days, users=[*WINDOWS_USERS, *WEB_USERS], sessions=sessions(), end_day=end_day)


if __name__ == "__main__":
    from tests.perf.conftest import ensure_cache

    meta = ensure_cache()
    print(f"perf cache ready: {meta['rows']} rows, ingest {meta['ingest_rate']:.0f} lines/s")
