import asyncio
import statistics
import time

import pytest

from tests.perf.conftest import record

# The first run builds the 200,000-row template (about a minute) inside the fixture: a long timeout (F03).
pytestmark = [pytest.mark.perf, pytest.mark.timeout(1800)]


async def test_purge_keeps_queries_fast(perf_purge):
    job, reader, recent = perf_purge.job, perf_purge.reader, perf_purge.recent_filter
    latencies: list[float] = []
    done = asyncio.Event()

    async def query_loop():
        while not done.is_set():
            t = time.perf_counter(); await asyncio.to_thread(reader.page, recent, None, 200)
            latencies.append(time.perf_counter() - t); await asyncio.sleep(0.05)

    q = asyncio.create_task(query_loop())
    res = await job.run_once("manual")
    done.set(); await q
    p95 = statistics.quantiles(latencies, n=20)[18]
    record("purge_query_p95", p95); record("purge_rows", res.index_rows); record("purge_sec", res.duration_ms / 1000)
    assert res.index_rows >= 90_000 and p95 < 0.300
    assert res.errors == [] and res.deleted_files == [f"2026-10-{d}.jsonl" for d in range(26, 31)]
    assert reader.count_before_day("2026-10-31") == 0
