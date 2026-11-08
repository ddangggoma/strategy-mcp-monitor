"""GPU readings for the board: the Task Manager-style percentage from fake PDH counters, the
status shape, the history, and a PC without GPU counters (no real GPU needed)."""
import time

import pytest

from app.monitor.bus import BoardBus
from app.monitor.gpu import GpuReader, GpuReading, aggregate, open_gpu_reader
from app.monitor.system import DiskReading, PsutilSource, ResourceReading, SystemSampler

IGPU = "luid_0x00000000_0x000124D1_phys_0"
DGPU = "luid_0x00000000_0x000128F7_phys_0"
SOFT = "luid_0x00000000_0x0001287B_phys_0"
HARDWARE = {(0, 0x124D1): 128 * 2**20, (0, 0x128F7): 2 * 2**30}  # DXGI: the software adapter is not listed


def eng(pid: int, adapter: str, eng_no: int, kind: str) -> str:
    return f"pid_{pid}_{adapter}_eng_{eng_no}_engtype_{kind}"


def test_the_percentage_is_the_busiest_engine_summed_over_processes():
    engines = {
        eng(10, DGPU, 0, "3D"): 30.0,
        eng(11, DGPU, 0, "3D"): 25.5,  # same engine, another process: 55.5
        eng(10, DGPU, 3, "VideoDecode"): 40.0,
        eng(12, IGPU, 0, "3D"): 20.0,
        eng(13, DGPU, 2, "Copy"): -1.0,  # a counter glitch never subtracts
    }
    r = aggregate(engines, {}, HARDWARE)
    assert r == GpuReading(percent=55.5, mem_used=None, mem_total=128 * 2**20 + 2 * 2**30)


def test_an_engine_over_100_is_capped_and_the_software_adapter_is_left_out():
    engines = {eng(1, DGPU, 0, "3D"): 70.0, eng(2, DGPU, 0, "3D"): 60.0, eng(3, SOFT, 0, "3D"): 99.0}
    memory = {IGPU: 0.0, DGPU: 512 * 2**20, SOFT: 4 * 2**30}
    r = aggregate(engines, memory, HARDWARE)
    assert r is not None
    assert r.percent == 100.0
    assert r.mem_used == 512 * 2**20  # the software adapter's "dedicated" memory is not a GPU's


def test_idle_hardware_reads_zero_and_no_hardware_reads_none():
    assert aggregate({}, {IGPU: 0.0}, HARDWARE) == GpuReading(0.0, 0, 128 * 2**20 + 2 * 2**30)
    # without DXGI every adapter the counters name counts, and the total is unknown
    assert aggregate({eng(1, IGPU, 0, "3D"): 12.34}, {IGPU: 2**20}, None) == GpuReading(12.3, 2**20, None)
    # a VM: counters exist but no adapter at all
    assert aggregate({}, {}, None) is None
    assert aggregate({eng(1, SOFT, 0, "3D"): 5.0}, {SOFT: 1.0}, {}) is None


class FakeCounters:
    """Collections in order; the constructor's baseline collection is assumed taken."""

    def __init__(self, *rounds: tuple[dict[str, float], dict[str, float]]) -> None:
        self.rounds = list(rounds)

    def collect(self) -> tuple[dict[str, float], dict[str, float]]:
        return self.rounds.pop(0)


def test_open_gpu_reader_never_raises():
    def broken() -> FakeCounters:
        raise OSError("PDH_CSTATUS_NO_OBJECT")  # no "GPU Engine" object on this Windows

    assert open_gpu_reader(broken, lambda: HARDWARE) is None
    assert open_gpu_reader(lambda: FakeCounters(), lambda: {}) is None  # only the software adapter
    reader = open_gpu_reader(lambda: FakeCounters(({eng(1, DGPU, 0, "3D"): 8.0}, {})), lambda: None)
    assert reader is not None and reader.read() == GpuReading(8.0, None, None)


def reading(mono: float, gpu: GpuReading | None) -> ResourceReading:
    return ResourceReading(
        cpu_percent=10.0, cpu_count=8, mem_total=16 * 2**30, mem_used=8 * 2**30, mem_percent=50.0,
        disks=(DiskReading("C:", 500 * 2**30, 200 * 2**30, 40.0),),
        net_sent=0, net_recv=0, boot_time=1_793_750_400.0, mono=mono, gpu=gpu,
    )


def test_the_status_carries_the_gpu_and_its_history(clock):
    bus = BoardBus()
    sub = bus.subscribe()  # anonymous: public, and nothing names the adapter
    sampler = SystemSampler(bus, clock, history=2)
    s = sampler.record(reading(1.0, GpuReading(37.46, 512 * 2**20, 2 * 2**30)))
    assert s["gpu"] == {"percent": 37.5, "memory": {"used": 512 * 2**20, "total": 2 * 2**30, "percent": 25.0}}
    assert s["history"]["gpu"] == [37.5]
    s = sampler.record(reading(2.0, GpuReading(5.0, 2**20, None)))
    assert s["gpu"] == {"percent": 5.0, "memory": {"used": 2**20, "total": None, "percent": None}}
    s = sampler.record(reading(3.0, GpuReading(6.0, None, None)))
    assert s["gpu"] == {"percent": 6.0, "memory": None}
    assert s["history"]["gpu"] == [5.0, 6.0]  # the same window as CPU and memory
    assert list(sub.events)[-1] == ("system", s)


def test_a_failing_gpu_read_leaves_only_the_gpu_out():
    class Failing:
        def read(self) -> GpuReading | None:
            raise OSError("PDH_INVALID_HANDLE")

    r = PsutilSource(gpu=Failing()).read()  # type: ignore[arg-type]
    assert r.gpu is None and r.cpu_count >= 1
    r = PsutilSource(gpu=GpuReader(FakeCounters(({eng(1, IGPU, 0, "3D"): 3.0}, {IGPU: 0.0})), HARDWARE)).read()
    assert r.gpu == GpuReading(3.0, 0, 128 * 2**20 + 2 * 2**30)
    assert PsutilSource(gpu=None).read().gpu is None


@pytest.mark.winlive
def test_this_pcs_gpu_counters_read_cleanly():
    """The real PDH counters and DXGI; skips on a PC without them (a VM, CI without a GPU)."""
    pytest.importorskip("win32pdh")
    from app.win.gpu import PdhGpuCounters, dxgi_hardware_adapters

    adapters = dxgi_hardware_adapters()
    try:
        counters = PdhGpuCounters()
    except Exception as e:
        pytest.skip(f"no GPU counters on this PC: {e}")
    try:
        time.sleep(1.0)  # a rate needs a span after the baseline
        reader = GpuReader(counters, adapters)
        r = reader.read()
        if r is None:
            pytest.skip("no hardware GPU on this PC")
        assert 0.0 <= r.percent <= 100.0
        assert r.mem_used is None or r.mem_used >= 0
        assert r.mem_total is None or r.mem_total > 0
        print(f"GPU {r.percent}% dedicated {r.mem_used} / {r.mem_total}, {len(adapters or {})} hardware adapter(s)")
    finally:
        counters.close()
