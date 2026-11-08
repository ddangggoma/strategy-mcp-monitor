"""This PC's GPUs through Windows itself, vendor-neutral: PDH counters and the DXGI adapter list.

``PdhGpuCounters`` reads the two counter sets Task Manager uses — ``\\GPU Engine(*)\\Utilization
Percentage`` (one instance per process and engine) and ``\\GPU Adapter Memory(*)\\Dedicated Usage``
(one per adapter) — with English counter paths, so a Korean Windows works too. Utilization is a
rate: PDH needs two collections, so the constructor takes the first and every ``collect`` after
it gives the share since the previous one. ``dxgi_hardware_adapters`` lists the hardware adapters'
LUIDs and dedicated memory (the software "Basic Render" adapter is left out). Nothing here reads an
adapter's name. Both block briefly: call them from a worker thread, never on the event loop.
"""

from __future__ import annotations

import ctypes
from typing import Any

from app.win import IS_WINDOWS

if IS_WINDOWS:
    import win32pdh

ENGINE_PATH = r"\GPU Engine(*)\Utilization Percentage"
MEMORY_PATH = r"\GPU Adapter Memory(*)\Dedicated Usage"

Luid = tuple[int, int]
"""An adapter's LUID as unsigned (HighPart, LowPart): how PDH instance names spell it ("luid_0x…_0x…")."""


class PdhGpuCounters:
    """The two GPU counter sets in one PDH query. Raises when this Windows has no GPU counters."""

    def __init__(self) -> None:
        self._query: Any = win32pdh.OpenQuery()
        try:
            self._engine: Any = win32pdh.AddEnglishCounter(self._query, ENGINE_PATH)
            self._memory: Any = win32pdh.AddEnglishCounter(self._query, MEMORY_PATH)
            win32pdh.CollectQueryData(self._query)  # the baseline of the first rate
        except BaseException:
            win32pdh.CloseQuery(self._query)
            raise

    def collect(self) -> tuple[dict[str, float], dict[str, float]]:
        """(engine instance → utilization %, adapter instance → dedicated bytes) since the last call."""
        win32pdh.CollectQueryData(self._query)
        return self._array(self._engine), self._array(self._memory)

    @staticmethod
    def _array(counter: Any) -> dict[str, float]:
        try:
            items = win32pdh.GetFormattedCounterArray(counter, win32pdh.PDH_FMT_DOUBLE | win32pdh.PDH_FMT_NOCAP100)
        except win32pdh.error:
            return {}  # no instance right now (no process uses the GPU): nothing to add up
        return {str(k): float(v) for k, v in items.items()}

    def close(self) -> None:
        win32pdh.CloseQuery(self._query)


class _Guid(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16), ("d4", ctypes.c_ubyte * 8)]


class _Luid(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_int32)]


class _AdapterDesc1(ctypes.Structure):
    """DXGI_ADAPTER_DESC1 (the description string is part of the layout but never read)."""

    _fields_ = [
        ("description", ctypes.c_wchar * 128),
        ("vendor_id", ctypes.c_uint),
        ("device_id", ctypes.c_uint),
        ("sub_sys_id", ctypes.c_uint),
        ("revision", ctypes.c_uint),
        ("dedicated_video_memory", ctypes.c_size_t),
        ("dedicated_system_memory", ctypes.c_size_t),
        ("shared_system_memory", ctypes.c_size_t),
        ("luid", _Luid),
        ("flags", ctypes.c_uint),
    ]


_IID_IDXGIFACTORY1 = _Guid(0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
_DXGI_ADAPTER_FLAG_SOFTWARE = 2
_RELEASE = 2  # IUnknown::Release
_ENUM_ADAPTERS1 = 12  # IDXGIFactory1::EnumAdapters1
_GET_DESC1 = 10  # IDXGIAdapter1::GetDesc1
_MAX_ADAPTERS = 16


def _method(obj: ctypes.c_void_p, index: int, *argtypes: Any) -> Any:
    """The COM method at vtable ``index`` of ``obj``, returning an HRESULT."""
    vtable = ctypes.cast(ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])  # type: ignore[attr-defined]


def _release(obj: ctypes.c_void_p) -> None:
    vtable = ctypes.cast(ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[_RELEASE])(obj)  # type: ignore[attr-defined]


def dxgi_hardware_adapters() -> dict[Luid, int] | None:
    """Hardware display adapters: LUID → dedicated video memory in bytes. None when DXGI is not there."""
    try:
        dxgi = ctypes.WinDLL("dxgi")  # type: ignore[attr-defined]
    except OSError:
        return None
    factory = ctypes.c_void_p()
    if dxgi.CreateDXGIFactory1(ctypes.byref(_IID_IDXGIFACTORY1), ctypes.byref(factory)) != 0 or not factory:
        return None
    adapters: dict[Luid, int] = {}
    try:
        enum = _method(factory, _ENUM_ADAPTERS1, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))
        for i in range(_MAX_ADAPTERS):
            adapter = ctypes.c_void_p()
            if enum(factory, i, ctypes.byref(adapter)) != 0:  # DXGI_ERROR_NOT_FOUND: no more
                break
            try:
                desc = _AdapterDesc1()
                if _method(adapter, _GET_DESC1, ctypes.POINTER(_AdapterDesc1))(adapter, ctypes.byref(desc)) != 0:
                    continue
                if desc.flags & _DXGI_ADAPTER_FLAG_SOFTWARE:
                    continue
                adapters[(desc.luid.high & 0xFFFFFFFF, desc.luid.low)] = int(desc.dedicated_video_memory)
            finally:
                _release(adapter)
    finally:
        _release(factory)
    return adapters
