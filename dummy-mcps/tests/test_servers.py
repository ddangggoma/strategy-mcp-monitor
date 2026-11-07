import subprocess, sys, time, httpx, pytest
from tests.helpers import (free_port, listener_pid, wait_listening, wait_port_free, kill_tree,
                           rpc, open_session, ROOT)

INIT = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}

EXPECTED = {
    "seoul_weather": ("seoul-weather", {"get_current_weather", "get_forecast"}),
    "calculator": ("calculator", {"add", "subtract", "multiply", "divide", "evaluate"}),
    "seoul_clock": ("seoul-clock", {"now_kst", "convert_timezone"}),
}


def start(module, port, *extra):
    return subprocess.Popen([sys.executable, "-m", module, "--port", str(port), *extra],
                            cwd=ROOT, stdin=subprocess.DEVNULL)


def stop(p, port):
    """Kill the launcher AND the real interpreter behind it; the port must be free afterwards."""
    kill_tree(p)
    assert wait_port_free(port), "server process leaked past teardown"


@pytest.fixture(params=sorted(EXPECTED))
def server(request, tmp_path):
    port = free_port()
    p = start(request.param, port, "--chaos", "--pid-file", str(tmp_path / "p.pid"))
    try:
        wait_listening(port)
        yield request.param, port, p, tmp_path
    finally:
        stop(p, port)


@pytest.fixture
def calc():
    port = free_port()
    p = start("calculator", port)
    try:
        wait_listening(port)
        yield port
    finally:
        stop(p, port)


def test_initialize_ping_tools(server):
    mod, port, _, _ = server
    init, _ = rpc(port, "initialize", INIT)
    assert init["result"]["serverInfo"]["name"] == EXPECTED[mod][0]
    sid = open_session(port)
    assert rpc(port, "ping", session=sid)[0]["result"] == {}
    tools = {t["name"] for t in rpc(port, "tools/list", session=sid)[0]["result"]["tools"]}
    assert tools == EXPECTED[mod][1]


def test_pid_file_is_listener(server):
    _, port, _, tmp = server
    assert int((tmp / "p.pid").read_text()) == listener_pid(port)


def test_calculator_evaluate_call(calc):
    sid = open_session(calc)
    res = rpc(calc, "tools/call", {"name": "evaluate", "arguments": {"expression": "1+2*3"}}, session=sid)[0]["result"]
    assert res.get("isError") in (None, False) and "7" in res["content"][0]["text"]


def test_calculator_arithmetic_calls(calc):
    sid = open_session(calc)
    for name, a, b, want in [("add", 2, 3, "5"), ("subtract", 2, 3, "-1"), ("multiply", 4, 2.5, "10"), ("divide", 7, 2, "3.5")]:
        res = rpc(calc, "tools/call", {"name": name, "arguments": {"a": a, "b": b}}, session=sid)[0]["result"]
        assert res.get("isError") in (None, False) and want in res["content"][0]["text"], name


@pytest.mark.parametrize("mod,tool,args,want", [
    ("seoul_weather", "get_current_weather", {"district": "강남구"}, "dummy"),
    ("seoul_clock", "now_kst", {}, "+09:00"),
])
def test_weather_and_clock_calls(mod, tool, args, want):
    port = free_port()
    p = start(mod, port)
    try:
        wait_listening(port)
        sid = open_session(port)
        res = rpc(port, "tools/call", {"name": tool, "arguments": args}, session=sid)[0]["result"]
        assert not res.get("isError") and want in res["content"][0]["text"]
    finally:
        stop(p, port)


def test_open_meteo_flag_only_on_weather():
    port = free_port()
    p = start("seoul_weather", port, "--open-meteo")
    try:
        wait_listening(port)  # flag parsed, server serving
    finally:
        stop(p, port)
    p = start("calculator", free_port(), "--open-meteo")
    try:
        assert p.wait(15) == 2  # argparse rejects the unknown flag
    finally:
        kill_tree(p)


def test_chaos_slow_then_crash(server):
    _, port, p, _ = server
    assert httpx.post(f"http://127.0.0.1:{port}/chaos/slow?ms=300").json() == {"slow_ms": 300}
    t = time.perf_counter(); rpc(port, "initialize", INIT)
    assert time.perf_counter() - t >= 0.3
    httpx.post(f"http://127.0.0.1:{port}/chaos/crash")
    assert p.wait(5) == 1


def test_chaos_range_validation(server):
    _, port, _, _ = server
    base = f"http://127.0.0.1:{port}/chaos"
    assert httpx.post(f"{base}/slow?ms=60001").status_code == 422
    assert httpx.post(f"{base}/slow?ms=-1").status_code == 422
    assert httpx.post(f"{base}/slow?ms=abc").status_code == 422
    assert httpx.post(f"{base}/hang?sec=0").status_code == 422
    assert httpx.post(f"{base}/hang?sec=3601").status_code == 422


def test_chaos_hang(server):
    _, port, _, _ = server
    httpx.post(f"http://127.0.0.1:{port}/chaos/hang?sec=3")
    time.sleep(0.3)
    with pytest.raises(httpx.TimeoutException):
        rpc(port, "ping", timeout=1.0)
    time.sleep(3)
    assert rpc(port, "initialize", INIT)[0]["result"]


def test_no_chaos_without_flag(calc):
    assert httpx.post(f"http://127.0.0.1:{calc}/chaos/crash").status_code == 404
    time.sleep(0.3)
    assert rpc(calc, "initialize", INIT)[0]["result"]  # still alive


def test_tool_error_carries_message(calc):
    sid = open_session(calc)
    res = rpc(calc, "tools/call", {"name": "divide", "arguments": {"a": 1, "b": 0}}, session=sid)[0]["result"]
    assert res["isError"] is True and "division by zero" in res["content"][0]["text"]
    res = rpc(calc, "tools/call", {"name": "evaluate", "arguments": {"expression": "__import__('os')"}}, session=sid)[0]["result"]
    assert res["isError"] is True and "disallowed" in res["content"][0]["text"]


@pytest.mark.skipif(sys.platform != "win32", reason="Ctrl+Break is Windows-specific")
def test_pid_file_removed_on_clean_exit(tmp_path):
    import signal
    port, pid_file = free_port(), tmp_path / "p.pid"
    p = subprocess.Popen([sys.executable, "-m", "calculator", "--port", str(port), "--pid-file", str(pid_file)],
                         cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    try:
        wait_listening(port)
        assert pid_file.exists()
        p.send_signal(signal.CTRL_BREAK_EVENT)
        assert wait_port_free(port, 10)
        deadline = time.monotonic() + 5
        while pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not pid_file.exists()
    finally:
        stop(p, port)


def test_pid_file_parent_dir_is_created(tmp_path):
    port = free_port()
    pid_file = tmp_path / "does" / "not" / "exist" / "p.pid"
    p = start("calculator", port, "--pid-file", str(pid_file))
    try:
        wait_listening(port)
        assert int(pid_file.read_text()) == listener_pid(port)
    finally:
        stop(p, port)


def test_second_instance_on_busy_port_keeps_first_pid_file(tmp_path):
    port, pid_file = free_port(), tmp_path / "p.pid"
    first = start("calculator", port, "--pid-file", str(pid_file))
    try:
        wait_listening(port)
        first_pid = pid_file.read_text()
        second = start("calculator", port, "--pid-file", str(pid_file))
        try:
            assert second.wait(30) != 0
        finally:
            kill_tree(second)
        assert pid_file.read_text() == first_pid == str(listener_pid(port))
    finally:
        stop(first, port)


def test_chaos_guard_rejects_foreign_host_and_origin(server):
    _, port, _, _ = server
    url = f"http://127.0.0.1:{port}/chaos/slow?ms=0"
    assert httpx.post(url).status_code == 200  # plain local client works
    assert httpx.post(url, headers={"Host": "evil.example"}).status_code == 403  # DNS rebinding
    assert httpx.post(url, headers={"Host": f"evil.example:{port}"}).status_code == 403
    assert httpx.post(url, headers={"Origin": "http://evil.example"}).status_code == 403  # cross-origin browser
    assert httpx.post(url, headers={"Origin": "null"}).status_code == 403
    # malformed Origins fail closed (403), never a 500
    for bad in ("http://[::1", "http://[evil"):
        assert httpx.post(url, headers={"Origin": bad}).status_code == 403, bad
    assert httpx.post(url, headers={"Origin": "http://localhost:3000"}).status_code == 200
    assert httpx.post(url, headers={"Host": f"localhost:{port}"}).status_code == 200
    assert httpx.post(url, headers={"Host": f"[::1]:{port}"}).status_code == 200
    # a rejected crash must not crash the server
    assert httpx.post(f"http://127.0.0.1:{port}/chaos/crash", headers={"Origin": "http://evil.example"}).status_code == 403
    time.sleep(0.5)
    assert rpc(port, "initialize", INIT)[0]["result"]
