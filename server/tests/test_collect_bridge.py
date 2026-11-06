import asyncio
import threading

import pytest

from app.collect.bridge import CollectorBridge
from tests.winfakes import ListLog, eventually


async def test_items_from_threads_reach_the_handler_on_the_loop_in_order():
    loop = asyncio.get_running_loop(); seen: list[tuple[int, list[int]]] = []
    bridge = CollectorBridge(loop, ListLog())
    post = bridge.register("wts", lambda items: seen.append((threading.get_ident(), list(items))))
    t = threading.Thread(target=lambda: [post(i) for i in range(100)]); t.start(); t.join()
    await eventually(lambda: sum(len(b) for _, b in seen) == 100)
    assert [x for _, batch in seen for x in batch] == list(range(100))
    assert {tid for tid, _ in seen} == {threading.get_ident()}


async def test_overflow_drops_oldest_and_logs_once():
    loop = asyncio.get_running_loop(); got: list[int] = []; log = ListLog()
    bridge = CollectorBridge(loop, log, max_pending=3)
    post = bridge.register("wmi", got.extend)
    t = threading.Thread(target=lambda: [post(i) for i in range(10)])
    t.start(); t.join()  # blocks the loop: nothing drains until the thread is done
    await eventually(lambda: got == [7, 8, 9])
    assert [(c, f) for c, _, f in log.events] == [("system", {"event": "collector.dropped", "source": "wmi", "count": 7})]


async def test_handler_exception_is_logged_and_other_handlers_still_run():
    loop = asyncio.get_running_loop(); ok: list[int] = []; log = ListLog()
    bridge = CollectorBridge(loop, log)
    bad = bridge.register("bad", lambda items: 1 / 0)
    good = bridge.register("good", ok.extend)
    bad(1); good(2)
    await eventually(lambda: ok == [2])
    assert log.events[0][2]["event"] == "collector.handler_failed" and log.events[0][2]["source"] == "bad"
    bad(3); good(4)
    await eventually(lambda: ok == [2, 4])


def test_register_twice_is_an_error():
    loop = asyncio.new_event_loop()
    try:
        bridge = CollectorBridge(loop, ListLog()); bridge.register("x", print)
        with pytest.raises(ValueError):
            bridge.register("x", print)
    finally:
        loop.close()


def test_post_after_loop_closed_is_ignored():
    loop = asyncio.new_event_loop(); bridge = CollectorBridge(loop, ListLog())
    post = bridge.register("x", print); loop.close()
    post(1)  # must not raise
