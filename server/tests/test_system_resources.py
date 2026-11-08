import asyncio
import json

from app.monitor.bus import BoardBus
from app.monitor.system import DiskReading, PsutilSource, ResourceReading, SystemSampler
from app.web.mcp_shared import board_stream


def reading(mono: float, sent: int = 0, recv: int = 0, cpu: float = 12.34, mem: float = 50.0) -> ResourceReading:
    return ResourceReading(
        cpu_percent=cpu, cpu_count=8, mem_total=16 * 2**30, mem_used=8 * 2**30, mem_percent=mem,
        disks=(DiskReading("C:", 500 * 2**30, 200 * 2**30, 40.0),),
        net_sent=sent, net_recv=recv, boot_time=1_793_750_400.0, mono=mono,
    )


class ListSource:
    def __init__(self, *readings: ResourceReading) -> None:
        self._readings = list(readings)

    def read(self) -> ResourceReading:
        return self._readings.pop(0) if len(self._readings) > 1 else self._readings[0]


def test_record_builds_the_status_and_publishes_it(clock):
    bus = BoardBus()
    sub = bus.subscribe()  # anonymous: the status is public
    sampler = SystemSampler(bus, clock)
    assert sampler.latest is None
    status = sampler.record(reading(10.0))
    assert status == {
        "at": "2026-11-04T14:00:00.000+09:00",
        "interval_sec": 5.0,
        "cpu": {"percent": 12.3, "cores": 8},
        "memory": {"total": 16 * 2**30, "used": 8 * 2**30, "percent": 50.0},
        "disks": [{"name": "C:", "total": 500 * 2**30, "used": 200 * 2**30, "percent": 40.0}],
        "network": None,  # a rate needs two readings
        "boot_at": "2026-11-04T09:00:00.000+09:00",
        "history": {"cpu": [12.3], "memory": [50.0]},
    }
    assert sampler.latest is status
    assert list(sub.events) == [("system", status)]


def test_network_rate_and_history_window(clock):
    sampler = SystemSampler(BoardBus(), clock, history=3)
    sampler.record(reading(10.0, sent=1_000, recv=5_000, cpu=1))
    s = sampler.record(reading(12.0, sent=3_000, recv=15_000, cpu=2))
    assert s["network"] == {"sent_bps": 1_000, "recv_bps": 5_000}
    s = sampler.record(reading(14.0, sent=0, recv=15_000, cpu=3))  # a counter reset reads as 0
    assert s["network"] == {"sent_bps": 0, "recv_bps": 0}
    s = sampler.record(reading(16.0, cpu=4))
    assert s["history"]["cpu"] == [2, 3, 4]  # the oldest fell out


async def test_board_and_stream_carry_the_status(services, external_client):
    assert "system" not in (await external_client.get("/api/board")).json()  # not read yet
    services.system.record(reading(1.0))
    body = (await external_client.get("/api/board")).json()
    assert body["system"]["cpu"] == {"percent": 12.3, "cores": 8}

    sub = services.bus.subscribe()
    gen = board_stream(services.monitor, services.bus, sub, coalesce_sec=0.01, heartbeat_sec=5)
    await anext(gen)  # the board
    services.system.record(reading(6.0, cpu=99.0))
    event = await asyncio.wait_for(anext(gen), 1)
    assert event.startswith("event: system\n")
    assert json.loads(event.split("data: ", 1)[1])["cpu"]["percent"] == 99.0
    await gen.aclose()


async def test_sampler_runs_until_stopped(clock):
    bus = BoardBus()
    sub = bus.subscribe()
    sampler = SystemSampler(bus, clock, ListSource(reading(1.0), reading(2.0)), interval_sec=0.01)
    await sampler.start()
    for _ in range(100):
        if len(sub.events) >= 2:
            break
        await asyncio.sleep(0.01)
    await sampler.stop()
    assert [name for name, _ in sub.events][:2] == ["system", "system"]
    assert sampler.latest is not None and sampler.latest["network"] is not None


async def test_a_failing_source_keeps_the_sampler_alive(clock):
    class Flaky:
        calls = 0

        def read(self) -> ResourceReading:
            self.calls += 1
            if self.calls == 1:
                raise OSError("busy")
            return reading(float(self.calls))

    sampler = SystemSampler(BoardBus(), clock, Flaky(), interval_sec=0.01)
    await sampler.start()
    for _ in range(100):
        if sampler.latest is not None:
            break
        await asyncio.sleep(0.01)
    await sampler.stop()
    assert sampler.latest is not None


def test_psutil_source_reads_this_pc():
    r = PsutilSource().read()
    assert r.cpu_count >= 1 and 0 <= r.cpu_percent <= 100
    assert r.mem_total > 0 and 0 < r.mem_used <= r.mem_total
    assert r.disks and all(d.total > 0 for d in r.disks)
    assert r.boot_time > 0
