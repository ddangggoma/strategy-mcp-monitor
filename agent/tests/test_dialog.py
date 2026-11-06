import ctypes
from pathlib import Path

import pytest

from mcp_agent.dialog import EdgeWindow, PrintWindow, edge_command
from mcp_agent.win32 import current_session_id, idle_seconds

def test_edge_command_line():
    assert edge_command(r"C:\Edge\msedge.exe", "http://127.0.0.1:8700/notice#d=1&t=x", Path(r"C:\p")) == [
        r"C:\Edge\msedge.exe", "--app=http://127.0.0.1:8700/notice#d=1&t=x", r"--user-data-dir=C:\p",
        "--no-first-run", "--no-default-browser-check", "--disable-sync", "--window-size=640,600"]

class FakeProc:
    def __init__(self, pid):
        self.pid, self.code = pid, None
    def poll(self):
        return self.code

class FakeOps:
    """Win32 side of EdgeWindow. ``windows``: hwnd -> owner pid (captioned "MCP Monitor") or
    (owner pid, caption); ``trees``: pid -> live descendants; ``alive``: live pids."""
    def __init__(self):
        self.windows, self.trees, self.alive, self.placed = {}, {}, set(), []
    def edge_windows(self):
        return {h: v if isinstance(v, tuple) else (v, "MCP Monitor") for h, v in self.windows.items()}
    def process_tree(self, pid):
        return [pid, *self.trees.get(pid, [])]
    def place(self, hwnd):
        self.placed.append(hwnd); return True
    def is_window(self, hwnd):
        return hwnd in self.windows
    def pid_alive(self, pid):
        return pid in self.alive

# C1/F10: the window is found by title across msedge processes, and "closed by the user" means
# that window is gone, not that the launched pid exited. Plan test adapted accordingly.
def test_edge_window_tracks_user_close_and_our_close(tmp_path):
    procs, killed, ops = [], [], FakeOps()
    def popen(argv, **kw):
        procs.append(FakeProc(100 + len(procs))); ops.windows[procs[-1].pid * 10] = procs[-1].pid; return procs[-1]
    w = EdgeWindow(r"C:\Edge\msedge.exe", tmp_path, popen=popen, kill_tree=killed.append, ops=ops)
    w.open("http://u/1", 1)
    assert not w.closed_by_user()
    del ops.windows[1000]; procs[0].code = 0  # the user closed the window and Edge exited
    assert w.closed_by_user()
    w.open("http://u/2", 2); w.close(); del ops.windows[1010]; procs[1].code = 1
    assert killed == [101] and not w.closed_by_user()
    assert ops.placed == [1000, 1010]  # first attempt is synchronous and succeeded, so no retry thread ran

def test_print_window_lines(tmp_path):
    w = PrintWindow(tmp_path / "u.url"); w.open("http://a", 3); w.close(); w.close()
    assert (tmp_path / "u.url").read_text("utf-8").splitlines() == ["OPEN 3 http://a", "CLOSE 3"] and not w.closed_by_user()

@pytest.mark.winlive
def test_session_id_and_idle_match_the_kernel():
    sid = ctypes.c_ulong()
    assert ctypes.windll.kernel32.ProcessIdToSessionId(ctypes.windll.kernel32.GetCurrentProcessId(), ctypes.byref(sid))
    assert current_session_id() == sid.value and idle_seconds() >= 0


# --- beyond the plan ---------------------------------------------------------------------------

import http.server  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import winreg  # noqa: E402

from mcp_agent import win32  # noqa: E402
from mcp_agent.dialog import find_edge, taskkill_tree  # noqa: E402


def wait_until(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < end, "condition not met"
        time.sleep(0.02)


def edge(ops, popen, killed=None, **kw):
    return EdgeWindow(r"C:\Edge\msedge.exe", Path(r"C:\p"), popen=popen, kill_tree=(killed if killed is not None else []).append,
                      ops=ops, **kw)


def test_launcher_exit_with_the_window_alive_is_not_a_user_close():
    # F10: Edge handed the URL to a browser process outside the launched tree and exited at once.
    ops, killed, argvs = FakeOps(), [], []
    def popen(argv, **kw):
        argvs.append(argv); p = FakeProc(100); p.code = 0; ops.windows[555] = 900; return p
    w = edge(ops, popen, killed)
    w.open("http://u/1", 1)
    assert argvs == [edge_command(r"C:\Edge\msedge.exe", "http://u/1", Path(r"C:\p"))]
    assert ops.placed == [555] and not w.closed_by_user()
    ops.alive = {900}
    w.close()
    assert killed == [900]  # the launched pid is gone; the window's owner is what we close
    ops.alive.clear()
    w.open("http://u/2", 2)
    del ops.windows[555]
    assert w.closed_by_user() is False  # 555 was there before this launch, so it is not this notice's window


def test_handed_off_window_closed_by_the_user():
    ops = FakeOps()
    def popen(argv, **kw):
        p = FakeProc(100); p.code = 0; ops.windows[555] = 900; return p
    w = edge(ops, popen)
    w.open("u", 1)
    del ops.windows[555]
    assert w.closed_by_user()


def test_a_window_in_the_launched_tree_wins_over_other_edge_windows():
    ops = FakeOps(); ops.trees[100] = [101, 102]
    def popen(argv, **kw):
        ops.windows.update({555: 900, 556: 102}); return FakeProc(100)
    w = edge(ops, popen)
    w.open("u", 1)
    assert ops.placed == [556]


def test_a_tree_window_is_ours_whatever_its_caption_but_others_need_the_title():
    ops = FakeOps(); ops.trees[100] = [101]
    def popen(argv, **kw):
        ops.windows.update({554: (900, "Other site"), 555: (101, ""), 556: (101, "127.0.0.1:8700/notice")}); return FakeProc(100)
    w = edge(ops, popen, retry_sec=0.01)
    w.open("u", 1)
    assert ops.placed == [556] and w.window_handle == 556  # empty captions (helper windows) are skipped
    ops2 = FakeOps()
    w2 = edge(ops2, lambda argv, **kw: ops2.windows.update({554: (900, "Other site")}) or FakeProc(100), retry_sec=0.01)
    w2.open("u", 1)
    time.sleep(0.05)
    assert ops2.placed == [] and w2.window_handle is None
    w2.close()


def test_an_unfound_window_counts_as_closed_only_once_edge_has_exited():
    ops, clock, killed = FakeOps(), [0.0], []
    ops.trees[100] = [101, 102]; ops.alive = {101, 102}
    def popen(argv, **kw):
        p = FakeProc(100); p.code = 0; return p  # the launcher hands over to its browser child 101
    w = edge(ops, popen, killed, locate_sec=5.0, retry_sec=0.01, monotonic=lambda: clock[0])
    w.open("u", 1)
    clock[0] = 6.0
    assert not w.closed_by_user()  # the browser still runs; its window may be captioned differently
    w.close()
    assert killed == [101, 102]  # orphaned browser tree, parents first (the fake kill does not end 102)
    ops.alive.clear()
    w.open("u", 2); clock[0] = 12.0  # this time Edge exits with no window found: the user closed it
    assert w.closed_by_user()


def test_close_kills_the_launcher_and_a_handed_off_owner():
    ops, killed = FakeOps(), []
    ops.alive = {900}
    def popen(argv, **kw):
        ops.windows[555] = 900; return FakeProc(100)  # launcher still running, window in another process
    w = edge(ops, popen, killed)
    w.open("u", 1); w.close()
    assert killed == [100, 900]


def test_windows_open_before_the_launch_are_not_adopted():
    ops = FakeOps(); ops.windows[777] = 900  # e.g. a stale notice window of a killed agent
    clock = [0.0]
    def popen(argv, **kw):
        p = FakeProc(100); p.code = 0; return p
    w = edge(ops, popen, locate_sec=5.0, retry_sec=0.01, monotonic=lambda: clock[0])
    w.open("u", 1)
    assert ops.placed == [] and not w.closed_by_user()  # launcher gone, but still within the locate window
    clock[0] = 5.0
    assert w.closed_by_user()  # no window ever appeared for this notice
    assert ops.placed == []


def test_the_retry_thread_places_a_window_that_appears_late():
    ops = FakeOps()
    w = edge(ops, lambda argv, **kw: FakeProc(100), retry_sec=0.01)
    w.open("u", 1)
    assert ops.placed == []
    ops.windows[1000] = 100
    wait_until(lambda: ops.placed == [1000])
    time.sleep(0.05)
    assert ops.placed == [1000] and not w.closed_by_user()
    del ops.windows[1000]
    assert w.closed_by_user()


def test_the_retry_thread_stops_after_our_close():
    ops = FakeOps()
    w = edge(ops, lambda argv, **kw: FakeProc(100), retry_sec=0.01)
    w.open("u", 1); w.close()
    ops.windows[1000] = 100
    time.sleep(0.1)
    assert ops.placed == [] and not w.closed_by_user()


def test_open_waits_for_the_previous_edge_to_exit():
    ops, sleeps, procs = FakeOps(), [], []
    def popen(argv, **kw):
        procs.append(FakeProc(100 + len(procs))); ops.windows[procs[-1].pid * 10] = procs[-1].pid
        ops.alive.add(procs[-1].pid); return procs[-1]
    def sleep(s):
        sleeps.append(s)
        if len(sleeps) == 3:
            ops.alive.discard(100)
    w = edge(ops, popen, sleep=sleep)
    w.open("u1", 1)
    w.open("u2", 2)  # closes 1 (kill), then waits for pid 100 to go before launching
    assert sleeps == [0.05, 0.05, 0.05] and [p.pid for p in procs] == [100, 101]


def test_open_gives_up_waiting_after_two_seconds():
    ops, clock, procs = FakeOps(), [0.0], []
    def popen(argv, **kw):
        procs.append(FakeProc(100 + len(procs))); ops.alive.add(procs[-1].pid); return procs[-1]
    def sleep(s):
        clock[0] += s
    w = edge(ops, popen, sleep=sleep, monotonic=lambda: clock[0], retry_sec=0.01, locate_sec=0.0)
    w.open("u1", 1)
    w.open("u2", 2)  # pid 100 never exits
    assert [p.pid for p in procs] == [100, 101] and 2.0 <= clock[0] < 2.1


def test_without_edge_the_default_browser_opens_and_nothing_is_tracked():
    opened, launched = [], []
    w = EdgeWindow(None, Path(r"C:\p"), popen=lambda *a, **k: launched.append(a), kill_tree=launched.append, ops=FakeOps(),
                   browser_open=opened.append)
    w.open("http://u/1", 1)
    w.close()
    assert opened == ["http://u/1"] and launched == [] and not w.closed_by_user()


def test_an_edge_that_fails_to_start_falls_back_to_the_default_browser():
    opened = []
    def popen(argv, **kw):
        raise FileNotFoundError(2, "missing", argv[0])
    w = EdgeWindow(r"D:\gone\msedge.exe", Path(r"C:\p"), popen=popen, kill_tree=opened.append, ops=FakeOps(),
                   browser_open=opened.append)
    w.open("http://u/1", 1)
    assert opened == ["http://u/1"] and w.window_handle is None and not w.closed_by_user()
    w.close()
    assert opened == ["http://u/1"]


def test_find_edge_prefers_app_paths_then_program_files():
    hklm, hkcu = winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER
    pf86 = r"C:\PF86\Microsoft\Edge\Application\msedge.exe"
    pf = r"C:\PF\Microsoft\Edge\Application\msedge.exe"
    env = {"ProgramFiles(x86)": r"C:\PF86", "ProgramFiles": r"C:\PF"}
    def find(reg, files):
        return find_edge(read_app_path=reg.get, environ=env, isfile=lambda p: p in files)
    assert find({hklm: r"C:\M\msedge.exe", hkcu: r"C:\U\msedge.exe"}, {r"C:\M\msedge.exe", r"C:\U\msedge.exe"}) == r"C:\M\msedge.exe"
    assert find({hklm: r"C:\M\msedge.exe", hkcu: r'"C:\U\msedge.exe"'}, {r"C:\U\msedge.exe"}) == r"C:\U\msedge.exe"
    assert find({}, {pf86, pf}) == pf86
    assert find({}, {pf}) == pf
    assert find({}, set()) is None


def test_find_edge_reads_the_registry_on_this_pc():
    found = find_edge()
    assert found is None or (found.lower().endswith("msedge.exe") and Path(found).is_file())


def test_process_tree_follows_an_exited_root_parents_first_and_filters_by_image(monkeypatch):
    # pid 1 (the launcher) is gone; its children still name it as their parent.
    snapshot = {10: (1, "msedge.exe"), 11: (10, "msedge.exe"), 12: (10, "notepad.exe"), 13: (11, "MSEDGE.EXE"),
                14: (99, "msedge.exe"), 15: (12, "msedge.exe")}
    monkeypatch.setattr(win32, "processes", lambda: snapshot)
    assert win32.process_tree(1) == [1, 10, 11, 12, 13, 15]
    assert win32.process_tree(1, image="msedge.exe") == [1, 10, 11, 13]


@pytest.mark.winlive
def test_process_tree_on_this_pc_contains_our_child():
    child = subprocess.Popen(["cmd", "/c", "ping -n 3 127.0.0.1 >nul"], creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        assert child.pid in win32.process_tree(os.getpid()) and win32.pid_alive(child.pid)
    finally:
        child.kill(); child.wait(5)
    assert not win32.pid_alive(child.pid)


def test_taskkill_tree_kills_the_whole_tree_without_a_console():
    calls = []
    taskkill_tree(42, run=lambda argv, **kw: calls.append((argv, kw)))
    assert calls == [(["taskkill", "/PID", "42", "/T", "/F"], {"creationflags": subprocess.CREATE_NO_WINDOW, "capture_output": True})]


class _NoticePage(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        data = b"<!doctype html><html><head><title>MCP Monitor</title></head><body>notice</body></html>"
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *a):
        pass


@pytest.fixture
def notice_page():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _NoticePage)
    t = threading.Thread(target=httpd.serve_forever, daemon=True); t.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/notice#d=1&t=x"
    finally:
        httpd.shutdown(); httpd.server_close()


@pytest.mark.winlive
def test_real_edge_app_window_is_found_topmost_and_closed(tmp_path, notice_page):
    path = find_edge()
    assert path, "Microsoft Edge is not installed on this PC"
    w = EdgeWindow(path, tmp_path / "profile")
    try:
        w.open(notice_page, 1)
        wait_until(lambda: w.window_handle is not None, 20)
        hwnd = w.window_handle
        ex_style = ctypes.WinDLL("user32").GetWindowLongW(ctypes.c_void_p(hwnd), -20)  # GWL_EXSTYLE
        assert ex_style & 0x8 and win32.is_window(hwnd)  # WS_EX_TOPMOST
        assert not w.closed_by_user()
        ctypes.WinDLL("user32").PostMessageW(ctypes.c_void_p(hwnd), 0x0010, 0, 0)  # WM_CLOSE, what the title bar X does
        wait_until(w.closed_by_user, 10)
        w.open(notice_page, 2)
        wait_until(lambda: w.window_handle is not None, 20)
        second = w.window_handle
    finally:
        w.close()
    wait_until(lambda: not win32.is_window(second), 10)
    assert not w.closed_by_user()
