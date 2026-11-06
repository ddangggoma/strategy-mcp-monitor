import asyncio
import json
import threading
import time
from datetime import UTC, datetime

import pytest

from app.logstore.writer import DailyJsonlWriter, LogWriter


def read(paths, day):
    return [json.loads(line) for line in (paths.logs_dir / f"{day}.jsonl").read_text("utf-8").splitlines()]


def test_batch_split_across_midnight(paths):
    w = DailyJsonlWriter(paths.logs_dir)
    w.write_batch([
        {"ts": "2026-11-04T23:59:59.999+09:00", "cat": "system", "msg": "a"},
        {"ts": "2026-11-04T15:00:00.000+00:00", "cat": "system", "msg": "b"},  # = 11-05 00:00 KST
    ])
    assert [e["msg"] for e in read(paths, "2026-11-04")] == ["a"]
    assert [e["msg"] for e in read(paths, "2026-11-05")] == ["b"]


def test_korean_not_escaped(paths):
    DailyJsonlWriter(paths.logs_dir).write_batch([{"ts": "2026-11-04T10:00:00.000+09:00", "cat": "system", "msg": "접속"}])
    assert "접속" in (paths.logs_dir / "2026-11-04.jsonl").read_text("utf-8")


async def test_emit_and_stop_flushes(paths, clock):
    lw = LogWriter(DailyJsonlWriter(paths.logs_dir), clock, flush_interval=60)
    await lw.start()
    for i in range(3):
        lw.emit("auth", n=i)
    await lw.stop()
    rows = read(paths, "2026-11-04")
    assert [r["n"] for r in rows] == [0, 1, 2]
    assert rows[0]["ts"] == "2026-11-04T14:00:00.000+09:00" and rows[0]["cat"] == "auth"


async def test_max_batch_triggers_write(paths, clock):
    lw = LogWriter(DailyJsonlWriter(paths.logs_dir), clock, flush_interval=60, max_batch=2)
    await lw.start()
    lw.emit("system", n=1); lw.emit("system", n=2)
    await lw.flush()
    assert len(read(paths, "2026-11-04")) == 2
    await lw.stop()


def test_lines_use_lf_and_default_separators(paths):
    DailyJsonlWriter(paths.logs_dir).write_batch([{"ts": "2026-11-04T10:00:00.000+09:00", "cat": "auth", "ok": False}])
    raw = (paths.logs_dir / "2026-11-04.jsonl").read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")
    assert b'"cat": "auth"' in raw and b'"ok": false' in raw


async def test_stop_is_idempotent_and_emit_never_raises(paths, clock):
    lw = LogWriter(DailyJsonlWriter(paths.logs_dir), clock, flush_interval=60)
    await lw.start()
    lw.emit("system", obj=object())  # not JSON-serializable by default; must not raise
    await lw.stop()
    await lw.stop()
    lw.emit("system", late=True)  # after stop: silently ignored, no raise
    assert len(read(paths, "2026-11-04")) == 1


async def test_write_failure_keeps_running_and_retries_once(paths, clock, capsys):
    logs = paths.logs_dir
    logs.rmdir()
    logs.write_text("not a directory")  # makes every write fail
    lw = LogWriter(DailyJsonlWriter(logs), clock, flush_interval=60)
    await lw.start()
    lw.emit("system", n=1)
    await lw.flush()  # fails; batch is kept for one retry
    assert "warning" in capsys.readouterr().err.lower()
    logs.unlink()
    logs.mkdir()
    lw.emit("system", n=2)
    await lw.flush()  # retried batch goes out first, then the new event
    await lw.stop()
    assert [r["n"] for r in read(paths, "2026-11-04")] == [1, 2]


async def test_batch_dropped_after_second_failure(paths, clock, capsys):
    logs = paths.logs_dir
    logs.rmdir()
    logs.write_text("not a directory")
    lw = LogWriter(DailyJsonlWriter(logs), clock, flush_interval=60)
    await lw.start()
    lw.emit("system", n=1)
    await lw.flush()
    await lw.flush()  # second failure: batch dropped
    assert "dropp" in capsys.readouterr().err.lower()
    logs.unlink()
    logs.mkdir()
    lw.emit("system", n=2)
    await lw.stop()
    rows = [(r.get("event"), r.get("count", r.get("n"))) for r in read(paths, "2026-11-04")]
    assert rows == [("logstore.dropped", 1), (None, 2)]  # the dropped batch is reported first


async def wait_for_rows(paths, day, count, timeout=2.0, until=None):
    """Poll (bounded) until the day's file holds at least `count` complete lines.

    Only "\\n"-terminated lines are parsed: a partially written last line is ignored.
    If `until` is given, also wait until `until(rows)` is true.
    """
    path = paths.logs_dir / f"{day}.jsonl"
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            lines = path.read_text("utf-8").split("\n")[:-1]  # drop the unterminated tail
        except OSError:
            lines = []
        if len(lines) >= count:
            rows = [json.loads(line) for line in lines]
            if until is None or until(rows):
                return rows
        await asyncio.sleep(0.01)
    raise AssertionError(f"{path.name}: condition not met within {timeout}s")


async def test_periodic_flush_without_flush_call(paths, clock):
    lw = LogWriter(DailyJsonlWriter(paths.logs_dir), clock, flush_interval=0.01)
    await lw.start()
    try:
        lw.emit("system", n=1)
        rows = await wait_for_rows(paths, "2026-11-04", 1)
        assert rows[0]["n"] == 1
    finally:
        await lw.stop()


async def test_max_batch_wakes_writer(paths, clock):
    lw = LogWriter(DailyJsonlWriter(paths.logs_dir), clock, flush_interval=60, max_batch=2)
    await lw.start()
    try:
        await asyncio.sleep(0)  # let the loop reach its wait
        lw.emit("system", n=1)
        lw.emit("system", n=2)
        rows = await wait_for_rows(paths, "2026-11-04", 2)
        assert [r["n"] for r in rows] == [1, 2]
    finally:
        await lw.stop()


async def test_background_loop_survives_write_failure(paths, clock, capsys):
    logs = paths.logs_dir
    logs.rmdir()
    logs.write_text("not a directory")
    lw = LogWriter(DailyJsonlWriter(logs), clock, flush_interval=0.01)
    await lw.start()
    try:
        lw.emit("system", n=1)
        # wait (bounded) for the background loop itself to hit the failure
        for _ in range(200):
            if "warning" in capsys.readouterr().err.lower():
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("background loop never attempted the write")
        assert not lw._task.done()
        logs.unlink()
        logs.mkdir()
        lw.emit("system", n=2)
        rows = await wait_for_rows(
            paths, "2026-11-04", 1, until=lambda rows: 2 in [r.get("n") for r in rows]
        )
        assert 2 in [r.get("n") for r in rows]
        assert not lw._task.done()
    finally:
        await lw.stop()


def test_bad_event_does_not_drop_batch(paths):
    circular: dict = {"ts": "2026-11-04T10:00:02.000+09:00", "cat": "system", "msg": "circ"}
    circular["self"] = circular
    DailyJsonlWriter(paths.logs_dir).write_batch([
        {"ts": "2026-11-04T10:00:00.000+09:00", "cat": "system", "msg": "good1"},
        circular,
        {"ts": "2026-11-04T10:00:03.000+09:00", "cat": "system", "msg": "bad\udc80surrogate"},
        {"ts": "2026-11-04T10:00:04.000+09:00", "cat": "system", "msg": "good2"},
    ])
    rows = read(paths, "2026-11-04")
    assert len(rows) == 4
    assert rows[0]["msg"] == "good1" and rows[3]["msg"] == "good2"
    assert "_unserializable" in rows[1] and rows[1]["cat"] == "system"
    assert rows[2]["cat"] == "system" and "surrogate" in rows[2]["msg"]


async def test_emit_at_overrides_timestamp_and_day(paths, clock):
    lw = LogWriter(DailyJsonlWriter(paths.logs_dir), clock, flush_interval=60)
    await lw.start()
    lw.emit("session", at=datetime(2026, 11, 3, 14, 59, 59, 500000, tzinfo=UTC), event="connect")  # 11-03 23:59:59.500 KST
    lw.emit("session", ts="2000-01-01T00:00:00+09:00", event="x")  # a ts field is still ignored
    await lw.stop()
    assert read(paths, "2026-11-03")[0]["ts"] == "2026-11-03T23:59:59.500+09:00"
    assert read(paths, "2026-11-04")[0]["ts"] == "2026-11-04T14:00:00.000+09:00"


async def test_emit_threadsafe_from_worker_thread(paths, clock):
    lw = LogWriter(DailyJsonlWriter(paths.logs_dir), clock, flush_interval=60)
    await lw.start()
    t = threading.Thread(target=lambda: [lw.emit_threadsafe("activity.process", n=i) for i in range(50)])
    t.start(); t.join()
    await asyncio.sleep(0.01)  # let the scheduled callbacks run
    await lw.stop()
    assert [r["n"] for r in read(paths, "2026-11-04")] == list(range(50))


async def test_emit_threadsafe_on_loop_thread_keeps_order(paths, clock):
    lw = LogWriter(DailyJsonlWriter(paths.logs_dir), clock, flush_interval=60)
    await lw.start()
    lw.emit_threadsafe("system", n=1); lw.emit("system", n=2)
    await lw.stop()
    assert [r["n"] for r in read(paths, "2026-11-04")] == [1, 2]


def test_emit_threadsafe_before_start_is_dropped_with_warning(paths, clock, capsys):
    lw = LogWriter(DailyJsonlWriter(paths.logs_dir), clock)
    lw.emit_threadsafe("system", n=1)
    assert "emit_threadsafe before start" in capsys.readouterr().err


def test_emit_threadsafe_after_loop_closed_is_dropped_with_warning(paths, clock, capsys):
    loop = asyncio.new_event_loop()
    lw = LogWriter(DailyJsonlWriter(paths.logs_dir), clock)
    loop.run_until_complete(lw.start()); loop.run_until_complete(lw.stop()); loop.close()
    t = threading.Thread(target=lambda: lw.emit_threadsafe("system", n=1)); t.start(); t.join()
    assert "emit_threadsafe after loop closed" in capsys.readouterr().err
    assert not (paths.logs_dir / "2026-11-04.jsonl").exists()


class FlakyDaily(DailyJsonlWriter):
    def __init__(self, d):
        super().__init__(d); self.fail = True

    def write_batch(self, events):
        if self.fail:
            raise OSError("disk full")
        super().write_batch(events)


class SlowDaily(DailyJsonlWriter):
    def write_batch(self, events):
        time.sleep(1.0); super().write_batch(events)


def lines(d):
    return [json.loads(x) for f in sorted(d.glob("*.jsonl")) for x in f.read_text("utf-8").split("\n") if x]


async def test_queue_is_bounded_and_drops_are_reported(tmp_path, clock, capsys):
    flaky = FlakyDaily(tmp_path)
    w = LogWriter(flaky, clock, flush_interval=0.01, max_batch=10, max_queue=50); await w.start()
    for i in range(200): w.emit("system", event="x", i=i)
    assert w.pending <= 60
    assert capsys.readouterr().err.count("log queue full; dropping oldest events") == 1
    await asyncio.sleep(0.1)
    flaky.fail = False; await w.flush(); await w.stop()
    got = lines(tmp_path)
    dropped = [e for e in got if e.get("event") == "logstore.dropped"]
    written = [e for e in got if e.get("event") == "x"]
    assert len(dropped) == 1 and dropped[0]["count"] + len(written) == 200
    assert all(e["i"] >= 150 for e in written)  # the bound dropped the oldest 150
    assert dropped[0]["cat"] == "system" and dropped[0]["ts"] == "2026-11-04T14:00:00.000+09:00"


async def test_dropped_count_survives_losing_its_own_report(tmp_path, clock):
    flaky = FlakyDaily(tmp_path)
    w = LogWriter(flaky, clock, flush_interval=60, max_batch=10, max_queue=5); await w.start()
    for i in range(8): w.emit("system", event="x", i=i)  # the 3 oldest are dropped
    await w.flush()  # [report(3), 3..7] fails and waits for its retry
    assert w.pending == 6
    await w.flush()  # the retry fails: report(3) and 5 events are lost -> a new report(8) waits
    assert w.pending == 1
    flaky.fail = False
    w.emit("system", event="x", i=8); await w.flush(); await w.stop()
    got = [(e["event"], e.get("i", e.get("count"))) for e in lines(tmp_path)]
    # the lost report is re-counted as the 3 events it carried, not as 1 lost line
    assert got == [("logstore.dropped", 8), ("x", 8)]


async def test_stop_warns_about_events_not_written(tmp_path, clock, capsys):
    w = LogWriter(FlakyDaily(tmp_path), clock, flush_interval=0.01); await w.start()
    for i in range(5): w.emit("system", event="x", i=i)
    await w.stop()
    assert "stop: 5 log event(s) were not written" in capsys.readouterr().err and w.stopped


async def test_stop_survives_cancellation(tmp_path, clock):
    w = LogWriter(SlowDaily(tmp_path), clock, flush_interval=0.01); await w.start()
    w.emit("system", event="x"); await asyncio.sleep(0.05)
    t = asyncio.create_task(w.stop()); await asyncio.sleep(0.05); t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t
    assert w.stopped and w._task is not None and w._task.done()
    w.emit("system", event="after")  # ignored, never raises
    assert w.pending <= 1


async def test_flush_listeners_run_after_each_successful_write(tmp_path, clock, capsys):
    calls = []
    w = LogWriter(DailyJsonlWriter(tmp_path), clock, flush_interval=0.01); await w.start()
    w.add_flush_listener(lambda: calls.append(1))
    w.add_flush_listener(lambda: 1 / 0)  # a failing listener does not stop the others
    w.add_flush_listener(lambda: calls.append(2))
    w.emit("system", event="x"); await w.flush(); await w.stop()
    assert calls[:2] == [1, 2]
    assert "flush listener failed: ZeroDivisionError" in capsys.readouterr().err


async def test_flush_listeners_skip_failed_writes(tmp_path, clock):
    calls = []
    flaky = FlakyDaily(tmp_path)
    w = LogWriter(flaky, clock, flush_interval=60); await w.start()
    w.add_flush_listener(lambda: calls.append(1))
    w.emit("system", event="x"); await w.flush()
    assert calls == [] and w.pending == 1  # held for its retry
    flaky.fail = False; await w.flush(); await w.stop()
    assert calls == [1] and w.pending == 0
