import pytest

from mcp_agent.hooks import WinEventHookThread


@pytest.mark.winlive
def test_hook_thread_installs_three_hooks_and_stops():
    got = []; t = WinEventHookThread(got.append); t.start()
    try:
        assert t.wait_ready(2.0) and t.hook_count == 3
    finally:
        t.stop()
    assert not t.is_alive()


# --- beyond the plan ---------------------------------------------------------------------------

import os  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

from mcp_agent import win32  # noqa: E402
from mcp_agent.coalesce import RawWinEvent  # noqa: E402
from mcp_agent.hooks import (  # noqa: E402
    EVENT_OBJECT_NAMECHANGE,
    EVENT_SYSTEM_FOREGROUND,
    EVENT_SYSTEM_MINIMIZEEND,
    EVENT_SYSTEM_MINIMIZESTART,
)

AT = datetime(2026, 11, 4, 4, 59, 57, tzinfo=UTC)


class FakeWin:
    def __init__(self):
        self.fg, self.titles, self.pids, self.images, self.image_calls = 5, {5: "doc", 6: "other"}, {5: 50, 6: 60}, \
            {50: r"C:\a.exe", 60: None}, []
    def text(self, hwnd): return self.titles[hwnd]
    def pid_of(self, hwnd): return self.pids[hwnd]
    def image(self, pid):
        self.image_calls.append(pid); return self.images[pid]


def make(fake, got, clock=None):
    clock = clock or [1.0]
    return WinEventHookThread(got.append, foreground=lambda: fake.fg, text=fake.text, pid_of=fake.pid_of,
                              image=fake.image, monotonic=lambda: clock[0], now=lambda: AT)


def test_callback_turns_foreground_and_minimize_events_into_raw_events():
    fake, got = FakeWin(), []
    t = make(fake, got)
    t.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0)
    t.handle(EVENT_SYSTEM_MINIMIZESTART, 6, 0, 0)
    t.handle(EVENT_SYSTEM_MINIMIZEEND, 6, 0, 0)
    assert got == [RawWinEvent(1.0, "foreground", 5, 50, r"C:\a.exe", "doc", AT),
                   RawWinEvent(1.0, "minimize", 6, 60, None, "other", AT),
                   RawWinEvent(1.0, "restore", 6, 60, None, "other", AT)]


def test_name_changes_count_only_for_the_foreground_window_itself():
    fake, got = FakeWin(), []
    t = make(fake, got)
    t.handle(EVENT_OBJECT_NAMECHANGE, 6, 0, 0)        # not the foreground window
    t.handle(EVENT_OBJECT_NAMECHANGE, 5, -4, 0)       # a child object (OBJID_CLIENT), not the window
    t.handle(EVENT_OBJECT_NAMECHANGE, 5, 0, 3)        # a child element
    t.handle(EVENT_SYSTEM_FOREGROUND, 0, 0, 0)        # no window
    assert got == []
    t.handle(EVENT_OBJECT_NAMECHANGE, 5, 0, 0)
    assert [(e.kind, e.hwnd, e.title) for e in got] == [("title", 5, "doc")]


def test_when_the_system_reports_no_foreground_window_the_last_foreground_event_counts():
    fake, got = FakeWin(), []
    fake.fg = 0
    t = make(fake, got)
    t.handle(EVENT_OBJECT_NAMECHANGE, 5, 0, 0)  # nothing known yet
    t.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0)
    t.handle(EVENT_OBJECT_NAMECHANGE, 6, 0, 0)
    t.handle(EVENT_OBJECT_NAMECHANGE, 5, 0, 0)
    assert [(e.kind, e.hwnd) for e in got] == [("foreground", 5), ("title", 5)]
    fake.fg = 6  # a real answer wins over the remembered window
    t.handle(EVENT_OBJECT_NAMECHANGE, 5, 0, 0); t.handle(EVENT_OBJECT_NAMECHANGE, 6, 0, 0)
    assert [(e.kind, e.hwnd) for e in got][2:] == [("title", 6)]


def test_process_image_is_cached_per_pid_for_a_while():
    fake, got, clock = FakeWin(), [], [1.0]
    t = make(fake, got, clock)
    t.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0); t.handle(EVENT_OBJECT_NAMECHANGE, 5, 0, 0)
    assert fake.image_calls == [50]
    clock[0] = 1000.0  # long enough for the pid to have been reused
    t.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0)
    assert fake.image_calls == [50, 50]


def test_callback_never_raises():
    fake, got = FakeWin(), []
    t = make(fake, got)
    fake.titles = {}  # text() raises KeyError
    t.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0)
    def boom(_e): raise RuntimeError("consumer failed")
    t2 = WinEventHookThread(boom, foreground=lambda: 5, text=fake.text, pid_of=fake.pid_of, image=fake.image)
    fake.titles = {5: "doc"}
    t2.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0)
    assert got == [] and t.errors == 1 and t2.errors == 1


def test_stop_before_start_and_twice_is_harmless():
    t = WinEventHookThread(lambda e: None)
    t.stop(); t.stop()
    assert not t.is_alive() and t.hook_count == 0 and not t.wait_ready(0.01)


@pytest.mark.winlive
def test_win32_window_and_process_helpers_on_this_pc():
    image = win32.process_image(os.getpid())
    assert image is not None and image.lower().endswith(".exe") and os.path.isabs(image)
    assert win32.process_image(0) is None  # the idle process cannot be opened
    hwnd = win32.foreground_window()
    assert isinstance(hwnd, int)
    if hwnd:  # a locked or disconnected desktop has no foreground window
        assert win32.window_pid(hwnd) > 0 and isinstance(win32.window_text(hwnd), str)
