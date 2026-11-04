import asyncio
import json

from app.logstore.writer import DailyJsonlWriter, LogWriter


def read(paths, day):
    return [json.loads(l) for l in (paths.logs_dir / f"{day}.jsonl").read_text("utf-8").splitlines()]


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
    assert [r["n"] for r in read(paths, "2026-11-04")] == [2]


async def wait_for_rows(paths, day, count, timeout=2.0):
    """Poll (bounded) until the day's file holds at least `count` complete lines."""
    path = paths.logs_dir / f"{day}.jsonl"
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            rows = path.read_text("utf-8").splitlines()
        except OSError:
            rows = []
        if len(rows) >= count:
            return [json.loads(l) for l in rows]
        await asyncio.sleep(0.01)
    raise AssertionError(f"{path.name}: fewer than {count} rows within {timeout}s")


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
        rows = await wait_for_rows(paths, "2026-11-04", 1)
        assert 2 in [r["n"] for r in rows]
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
