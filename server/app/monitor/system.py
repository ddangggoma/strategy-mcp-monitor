"""This PC's resources for the board: CPU, memory, GPU, fixed disks, network rate and boot time.

``SystemSampler`` reads them every ``interval_sec`` (in a worker thread: psutil may block for a
moment on a busy disk, PDH for a moment on the GPU counters), keeps the last ``history`` CPU,
memory and GPU percentages, and publishes the whole status as the public SSE ``system`` event;
``latest`` is the board snapshot's ``system``. ``gpu`` is None on a PC without GPU counters (see
``app.monitor.gpu`` for what the percentage means). Nothing that names the machine, its users, its
addresses or its GPU model is read (the board is anonymous).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import psutil

from app.clock import Clock, to_kst_iso
from app.monitor.bus import BoardBus
from app.monitor.gpu import GpuReader, GpuReading, open_gpu_reader

INTERVAL_SEC = 5.0
HISTORY = 60  # five minutes at the default interval
MAX_DISKS = 4

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiskReading:
    name: str
    total: int
    used: int
    percent: float


@dataclass(frozen=True)
class ResourceReading:
    cpu_percent: float
    cpu_count: int
    mem_total: int
    mem_used: int
    mem_percent: float
    disks: tuple[DiskReading, ...]
    net_sent: int
    net_recv: int
    boot_time: float
    """Epoch seconds."""
    mono: float
    """``time.monotonic()`` at the reading: the network rate's time base."""
    gpu: GpuReading | None = None
    """None on a PC without GPU counters."""


class ResourceSource(Protocol):
    def read(self) -> ResourceReading: ...


def _fixed_disks() -> tuple[DiskReading, ...]:
    """Local fixed drives ("C:"), at most ``MAX_DISKS``; a drive that cannot be read is skipped."""
    disks: list[DiskReading] = []
    for part in psutil.disk_partitions(all=False):
        if os.name == "nt" and "fixed" not in part.opts.split(","):
            continue  # removable, optical and network drives can hang or come and go
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        name = part.device.rstrip("\\/") or part.mountpoint
        disks.append(DiskReading(name, usage.total, usage.used, usage.percent))
        if len(disks) == MAX_DISKS:
            break
    return tuple(disks)


class PsutilSource:
    def __init__(self, gpu: GpuReader | None | Literal["auto"] = "auto") -> None:
        psutil.cpu_percent(interval=None)  # the first call only sets the baseline
        # the GPU counters' first collection is their baseline too
        self._gpu = open_gpu_reader() if gpu == "auto" else gpu
        self._gpu_failing = False

    def _read_gpu(self) -> GpuReading | None:
        """The GPU reading; a failing read leaves only the GPU out (logged once per run of failures)."""
        if self._gpu is None:
            return None
        try:
            reading = self._gpu.read()
        except Exception:
            if not self._gpu_failing:
                _log.warning("reading the GPU counters failed", exc_info=True)
            self._gpu_failing = True
            return None
        self._gpu_failing = False
        return reading

    def read(self) -> ResourceReading:
        mem = psutil.virtual_memory()
        net = psutil.net_io_counters()
        return ResourceReading(
            cpu_percent=psutil.cpu_percent(interval=None),
            cpu_count=psutil.cpu_count(logical=True) or 1,
            mem_total=mem.total,
            mem_used=mem.total - mem.available,  # what Task Manager calls "사용 중"
            mem_percent=mem.percent,
            disks=_fixed_disks(),
            net_sent=net.bytes_sent if net else 0,
            net_recv=net.bytes_recv if net else 0,
            boot_time=psutil.boot_time(),
            mono=time.monotonic(),
            gpu=self._read_gpu(),
        )


def _gpu_status(g: GpuReading | None) -> dict[str, Any] | None:
    """The status's ``gpu``: the percentage, and the dedicated memory when the counters tell it
    (``total`` and its ``percent`` only when DXGI told the adapters' size)."""
    if g is None:
        return None
    memory = None
    if g.mem_used is not None:
        total = g.mem_total
        memory = {
            "used": g.mem_used,
            "total": total,
            "percent": round(min(100.0, g.mem_used * 100 / total), 1) if total else None,
        }
    return {"percent": round(g.percent, 1), "memory": memory}


class SystemSampler:
    def __init__(
        self,
        bus: BoardBus,
        clock: Clock,
        source: ResourceSource | None = None,
        *,
        interval_sec: float = INTERVAL_SEC,
        history: int = HISTORY,
    ) -> None:
        self._bus = bus
        self._clock = clock
        self._source = source
        self._interval = interval_sec
        self._cpu: deque[float] = deque(maxlen=history)
        self._mem: deque[float] = deque(maxlen=history)
        self._gpu: deque[float] = deque(maxlen=history)
        self._prev: ResourceReading | None = None
        self._latest: dict[str, Any] | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def latest(self) -> dict[str, Any] | None:
        """The last status (None before the first reading): the board snapshot's ``system``."""
        return self._latest

    def record(self, r: ResourceReading) -> dict[str, Any]:
        """Take one reading: update the history and the rates, publish and return the status."""
        self._cpu.append(round(r.cpu_percent, 1))
        self._mem.append(round(r.mem_percent, 1))
        if r.gpu is not None:
            self._gpu.append(round(r.gpu.percent, 1))
        network = None
        prev = self._prev
        if prev is not None and r.mono > prev.mono:
            span = r.mono - prev.mono
            network = {  # a counter that went back (adapter reset) reads as 0, not negative
                "sent_bps": max(0, round((r.net_sent - prev.net_sent) / span)),
                "recv_bps": max(0, round((r.net_recv - prev.net_recv) / span)),
            }
        self._prev = r
        status: dict[str, Any] = {
            "at": to_kst_iso(self._clock.now()),
            "interval_sec": self._interval,
            "cpu": {"percent": round(r.cpu_percent, 1), "cores": r.cpu_count},
            "memory": {"total": r.mem_total, "used": r.mem_used, "percent": round(r.mem_percent, 1)},
            "disks": [
                {"name": d.name, "total": d.total, "used": d.used, "percent": round(d.percent, 1)}
                for d in r.disks
            ],
            "network": network,
            "boot_at": to_kst_iso(datetime.fromtimestamp(r.boot_time, UTC)),
            "gpu": _gpu_status(r.gpu),
            "history": {"cpu": list(self._cpu), "memory": list(self._mem), "gpu": list(self._gpu)},
        }
        self._latest = status
        self._bus.publish("system", status)
        return status

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="system-sampler")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _run(self) -> None:
        failing = False
        while True:
            try:
                if self._source is None:
                    self._source = await asyncio.to_thread(PsutilSource)
                    await asyncio.sleep(min(1.0, self._interval))  # a CPU share needs a span
                reading = await asyncio.to_thread(self._source.read)
            except Exception:
                if not failing:  # once per run of failures, not every five seconds
                    _log.exception("reading the PC's resources failed")
                failing = True
            else:
                failing = False
                self.record(reading)  # on the loop thread: the bus is not thread-safe
            await asyncio.sleep(self._interval)
