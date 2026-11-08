"""This PC's GPU load for the board, from per-engine counters (see ``app.win.gpu`` for the source).

The one percentage is what Task Manager shows as a GPU's utilization: each engine of an adapter
(3D, Copy, Video Decode, Compute, …) is busy for some share of the interval, summed over the
processes using it (capped at 100), and the GPU's figure is its **busiest engine**. With several
hardware adapters (a laptop's integrated and discrete GPU) the board shows the busiest one, so a
saturated GPU is never averaged away. Memory is the dedicated (on-board) memory in use, added up
over the hardware adapters, against their total when DXGI tells it (an integrated GPU has little or
none: it uses shared system memory, which the memory tile already counts).

``GpuReader`` turns raw counters into a ``GpuReading`` and returns None when this PC shows no GPU
(a VM or a server with only the software adapter, or a Windows without the counters): the board
then has no GPU block. Adapter names are never read (the board is anonymous).
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

Luid = tuple[int, int]

# pid_1234_luid_0x00000000_0x000124D1_phys_0_eng_3_engtype_VideoDecode
_ENGINE = re.compile(r"luid_(0x[0-9a-f]+)_(0x[0-9a-f]+)_phys_(\d+)_eng_(\d+)_", re.IGNORECASE)
# luid_0x00000000_0x000124D1_phys_0
_ADAPTER = re.compile(r"luid_(0x[0-9a-f]+)_(0x[0-9a-f]+)_phys_\d+", re.IGNORECASE)


@dataclass(frozen=True)
class GpuReading:
    percent: float
    """The busiest engine of the busiest hardware adapter, 0–100."""
    mem_used: int | None
    """Dedicated memory in use, bytes (None without the memory counters)."""
    mem_total: int | None
    """Dedicated memory of the hardware adapters, bytes (None when DXGI does not tell)."""


class GpuCounters(Protocol):
    def collect(self) -> tuple[dict[str, float], dict[str, float]]:
        """(engine instance → utilization %, adapter instance → dedicated bytes) since the last call."""
        ...


def _luid(match: re.Match[str]) -> Luid:
    return int(match.group(1), 16), int(match.group(2), 16)


def aggregate(engines: dict[str, float], memory: dict[str, float], hardware: dict[Luid, int] | None) -> GpuReading | None:
    """One reading from raw counters. ``hardware``: the hardware adapters (LUID → dedicated bytes) from
    DXGI, or None when unknown (then every adapter the counters name counts)."""
    def counts(luid: Luid) -> bool:
        return hardware is None or luid in hardware

    busy: dict[tuple[Luid, str, str], float] = {}  # (adapter, phys, engine) → summed over processes
    for name, value in engines.items():
        m = _ENGINE.search(name)
        if m is None or not counts(_luid(m)):
            continue
        key = (_luid(m), m.group(3), m.group(4))
        busy[key] = busy.get(key, 0.0) + max(0.0, value)
    used: int | None = None
    seen: set[Luid] = {k[0] for k in busy}
    for name, value in memory.items():
        m = _ADAPTER.search(name)
        if m is None or not counts(_luid(m)):
            continue
        seen.add(_luid(m))
        used = (used or 0) + max(0, int(value))
    if hardware is not None:
        seen |= set(hardware)
    if not seen:
        return None  # no hardware GPU on this PC (or no counters naming one)
    percent = min(100.0, max(busy.values(), default=0.0))
    total = sum(hardware.values()) if hardware else None
    return GpuReading(percent=round(percent, 1), mem_used=used, mem_total=total or None)


class GpuReader:
    """Raw counters → readings. ``counters`` already took its first collection (the rate baseline)."""

    def __init__(self, counters: GpuCounters, hardware: dict[Luid, int] | None) -> None:
        self._counters = counters
        self._hardware = hardware

    def read(self) -> GpuReading | None:
        engines, memory = self._counters.collect()
        return aggregate(engines, memory, self._hardware)


def open_gpu_reader(
    counters: Callable[[], GpuCounters] | None = None,
    hardware: Callable[[], dict[Luid, int] | None] | None = None,
) -> GpuReader | None:
    """The reader of this PC, or None when it has no GPU counters (not Windows, a VM, a trimmed
    Windows) or DXGI lists no hardware adapter. Never raises."""
    try:
        if counters is None or hardware is None:
            from app.win import IS_WINDOWS

            if not IS_WINDOWS:
                return None
            from app.win.gpu import PdhGpuCounters, dxgi_hardware_adapters

            counters = counters or PdhGpuCounters
            hardware = hardware or dxgi_hardware_adapters
        adapters = hardware()
        if adapters is not None and not adapters:
            return None  # only the software adapter
        return GpuReader(counters(), adapters)
    except Exception:
        return None
