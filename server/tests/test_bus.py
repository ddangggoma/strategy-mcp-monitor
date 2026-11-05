import pytest

from app.monitor.bus import BoardBus, IpStreamLimitError, StreamLimitError


def test_dirty_and_events():
    bus = BoardBus()
    sub = bus.subscribe()
    bus.mark_dirty(3)
    bus.mark_dirty(3)
    bus.publish("action", {"run_id": "r"})
    assert sub.dirty == {3} and list(sub.events) == [("action", {"run_id": "r"})] and sub.wake.is_set()


def test_events_bounded_and_limit():
    bus = BoardBus(max_streams=1)
    sub = bus.subscribe()
    for i in range(150):
        bus.publish("action", {"i": i})
    assert len(sub.events) == 100 and sub.events[0][1] == {"i": 50}
    with pytest.raises(StreamLimitError):
        bus.subscribe()
    bus.unsubscribe(sub)
    assert bus.subscriber_count == 0


def test_default_max_streams_is_100():
    bus = BoardBus()
    subs = [bus.subscribe() for _ in range(100)]
    with pytest.raises(StreamLimitError):
        bus.subscribe()
    bus.unsubscribe(subs[0])
    bus.subscribe()  # a freed slot is reusable
    assert bus.subscriber_count == 100


def test_unsubscribe_is_idempotent_and_releases_in_finally():
    bus = BoardBus(max_streams=1)
    sub = bus.subscribe()
    try:
        raise RuntimeError("client aborted")
    except RuntimeError:
        pass
    finally:
        bus.unsubscribe(sub)
        bus.unsubscribe(sub)  # second call is a no-op
    assert bus.subscriber_count == 0
    bus.subscribe()  # slot is free again


def test_non_public_events_only_reach_authed_subscribers():
    bus = BoardBus()
    anon, authed = bus.subscribe(), bus.subscribe(authed=True)
    bus.publish("action", {"run_id": "r", "exit_code": 1}, public=False)
    bus.publish("board", {"x": 1})
    assert [e for e, _ in anon.events] == ["board"]
    assert [e for e, _ in authed.events] == ["action", "board"]


def test_non_public_event_does_not_wake_anonymous():
    bus = BoardBus()
    anon = bus.subscribe()
    bus.publish("action", {"run_id": "r"}, public=False)
    assert not anon.wake.is_set() and not anon.events


def test_slow_subscriber_does_not_block_others_or_publisher():
    bus = BoardBus()
    slow, fast = bus.subscribe(), bus.subscribe()
    for i in range(1000):  # slow never drains; publish must still return immediately
        bus.publish("action", {"i": i})
        bus.mark_dirty(i % 5)
        if i % 10 == 0:
            fast.events.clear()
    assert len(slow.events) == 100 and slow.events[-1][1] == {"i": 999}
    assert slow.dirty == {0, 1, 2, 3, 4} and fast.events[-1][1] == {"i": 999}


def test_published_payload_is_copied():
    bus = BoardBus()
    sub = bus.subscribe()
    data = {"a": 1}
    bus.publish("e", data)
    data["a"] = 2
    assert sub.events[0][1] == {"a": 1}


def test_per_ip_cap_and_pre_flight_check():
    bus = BoardBus(max_streams=10, max_per_ip=2)
    a1, a2 = bus.subscribe(ip="1.1.1.1"), bus.subscribe(ip="1.1.1.1")
    with pytest.raises(IpStreamLimitError):
        bus.subscribe(ip="1.1.1.1")
    with pytest.raises(IpStreamLimitError):
        bus.check_capacity("1.1.1.1")  # the pre-flight check agrees and adds nothing
    bus.check_capacity("2.2.2.2"); bus.subscribe(ip="2.2.2.2"); bus.subscribe()  # other addresses / unknown ip unaffected
    assert bus.subscriber_count == 4
    bus.unsubscribe(a1)
    bus.subscribe(ip="1.1.1.1")  # a freed slot is reusable
    assert issubclass(IpStreamLimitError, StreamLimitError) and a2 in bus._subs


@pytest.mark.parametrize("ip,cap", [("127.0.0.1", 20), ("::1", 20), ("10.0.0.5", 5), ("not-an-ip", 5)])
def test_loopback_has_a_higher_per_ip_cap(ip, cap):
    bus = BoardBus()
    for _ in range(cap):
        bus.subscribe(ip=ip)
    with pytest.raises(IpStreamLimitError):
        bus.subscribe(ip=ip)
    with pytest.raises(IpStreamLimitError):
        bus.check_capacity(ip)
    assert bus.subscriber_count == cap


def test_loopback_cap_is_configurable_and_independent_of_other_ips():
    bus = BoardBus(max_per_ip=1, max_per_loopback=3)
    for _ in range(3):
        bus.subscribe(ip="127.0.0.1")
    with pytest.raises(IpStreamLimitError):
        bus.subscribe(ip="127.0.0.1")
    bus.subscribe(ip="10.0.0.5")  # a non-loopback address keeps its own, lower cap
    with pytest.raises(IpStreamLimitError):
        bus.subscribe(ip="10.0.0.5")


def test_global_cap_wins_over_ip_cap():
    bus = BoardBus(max_streams=1, max_per_ip=5)
    bus.subscribe(ip="1.1.1.1")
    with pytest.raises(StreamLimitError) as e:
        bus.subscribe(ip="2.2.2.2")
    assert not isinstance(e.value, IpStreamLimitError)
