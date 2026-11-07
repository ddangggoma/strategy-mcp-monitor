from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import socket
import time
from dataclasses import dataclass
from typing import Any

import httpx
import psutil

import app
from app.clock import Clock
from app.monitor.models import CheckResult, Issue, Mcp

PROBE_TIMEOUT_SEC = 3.0
MAX_RESPONSE_BYTES = 65_536
MCP_PROTOCOL_VERSION = "2025-06-18"
PORT_CACHE_TTL_SEC = 0.5

_PING_RE = re.compile(r"[=<](\d+)ms\s+TTL=")
_CLIENT_INFO = {"name": "mcp-monitor", "version": app.__version__}


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    latency_ms: float | None
    error: str | None  # timeout | connect | http_<status> | rpc_error | bad_response | too_large | no_reply


def _ms_since(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _fail(error: str) -> ProbeResult:
    return ProbeResult(False, None, error)


class _ProbeError(Exception):
    def __init__(self, error: str) -> None:
        super().__init__(error)
        self.error = error


@dataclass
class _Session:
    session_id: str | None
    protocol_version: str


def _message_with_id(payload: Any, want_id: int) -> dict | None:
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        if isinstance(item, dict) and item.get("id") == want_id and ("result" in item or "error" in item):
            return item
    return None


def _sse_event_data(event_lines: list[str]) -> str:
    return "\n".join(line[5:].removeprefix(" ") for line in event_lines if line.startswith("data:"))


class McpPingClient:
    """MCP `ping` over streamable HTTP. Initializes once per URL and reuses the session afterwards."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http
        self._sessions: dict[str, _Session] = {}
        self._next_id = 0

    def forget(self, url: str) -> None:
        self._sessions.pop(url, None)

    async def ping(self, url: str, timeout: float) -> ProbeResult:
        try:
            async with asyncio.timeout(timeout):
                return await self._ping(url)
        except _ProbeError as exc:
            return _fail(exc.error)
        except TimeoutError:
            return _fail("timeout")
        except httpx.TimeoutException:
            return _fail("timeout")
        except httpx.RemoteProtocolError:
            return _fail("bad_response")
        except httpx.NetworkError:
            return _fail("connect")
        except (httpx.HTTPError, httpx.InvalidURL):
            return _fail("bad_response")

    async def _ping(self, url: str) -> ProbeResult:
        session = self._sessions.get(url)
        cached = session is not None
        if session is None:
            session = await self._initialize(url)
        while True:
            start = time.perf_counter()
            status, message = await self._rpc(url, session, "ping")
            latency = _ms_since(start)
            if status == 404 and cached:  # the server forgot our session: initialize again, once
                self.forget(url)
                session = await self._initialize(url)
                cached = False
                continue
            self._check(status, message)
            return ProbeResult(True, latency, None)

    async def _initialize(self, url: str) -> _Session:
        params = {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {}, "clientInfo": _CLIENT_INFO}
        status, message, headers = await self._post(url, _Session(None, MCP_PROTOCOL_VERSION), "initialize", params)
        self._check(status, message)
        result = message.get("result") if message else None
        version = result.get("protocolVersion") if isinstance(result, dict) else None
        session = _Session(headers.get("mcp-session-id"), version if isinstance(version, str) else MCP_PROTOCOL_VERSION)
        status, _, _ = await self._post(url, session, "notifications/initialized", None, notification=True)
        if status >= 400:
            raise _ProbeError(f"http_{status}")
        self._sessions[url] = session
        return session

    async def _rpc(self, url: str, session: _Session, method: str) -> tuple[int, dict | None]:
        status, message, _ = await self._post(url, session, method, None)
        return status, message

    @staticmethod
    def _check(status: int, message: dict | None) -> None:
        if status >= 400:
            raise _ProbeError(f"http_{status}")
        if message is None:
            raise _ProbeError("no_reply")
        if "error" in message:
            raise _ProbeError("rpc_error")

    async def _post(
        self, url: str, session: _Session, method: str, params: dict | None, *, notification: bool = False
    ) -> tuple[int, dict | None, httpx.Headers]:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notification:
            self._next_id += 1
            body["id"] = self._next_id
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if session.session_id:
            headers["Mcp-Session-Id"] = session.session_id
        if method != "initialize":
            headers["MCP-Protocol-Version"] = session.protocol_version
        async with self._http.stream("POST", url, content=json.dumps(body), headers=headers) as response:
            if response.status_code >= 400 or notification:
                return response.status_code, None, response.headers  # body unread: closing the stream drops it
            content_type = response.headers.get("content-type", "")
            if content_type.startswith("text/event-stream"):
                message = await self._read_sse(response, body["id"])
            else:
                message = await self._read_json(response, body["id"])
            return response.status_code, message, response.headers

    @staticmethod
    async def _read_json(response: httpx.Response, want_id: int) -> dict | None:
        raw = bytearray()
        async for chunk in response.aiter_bytes():
            raw += chunk
            if len(raw) > MAX_RESPONSE_BYTES:
                raise _ProbeError("too_large")
        if not raw.strip():
            return None
        try:
            payload = json.loads(raw)
        except ValueError:
            raise _ProbeError("bad_response") from None
        if not isinstance(payload, (dict, list)):
            raise _ProbeError("bad_response")
        return _message_with_id(payload, want_id)

    @staticmethod
    async def _read_sse(response: httpx.Response, want_id: int) -> dict | None:
        """Return the reply with `want_id` as soon as its event is complete (the stream may stay open)."""
        total = 0
        buffer = ""
        event: list[str] = []
        async for text in response.aiter_text():
            total += len(text.encode())
            if total > MAX_RESPONSE_BYTES:
                raise _ProbeError("too_large")
            buffer += text
            held = "\r" if buffer.endswith("\r") else ""  # may be the first half of a CRLF
            *lines, rest = buffer[: len(buffer) - len(held)].replace("\r\n", "\n").replace("\r", "\n").split("\n")
            buffer = rest + held
            for line in lines:
                if line:
                    event.append(line)
                    continue
                data, event = _sse_event_data(event), []
                if not data.strip():
                    continue  # keep-alive / priming event without data
                try:
                    payload = json.loads(data)
                except ValueError:
                    raise _ProbeError("bad_response") from None
                message = _message_with_id(payload, want_id)
                if message is not None:
                    return message
        return None


async def probe_tcp(host: str, port: int, timeout: float) -> ProbeResult:
    start = time.perf_counter()
    try:
        async with asyncio.timeout(timeout):
            _, writer = await asyncio.open_connection(host, port)
    except TimeoutError:
        return _fail("timeout")
    except OSError:
        return _fail("connect")
    latency = _ms_since(start)
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return ProbeResult(True, latency, None)


def parse_ping_output(text: str) -> float | None:
    match = _PING_RE.search(text)
    return float(match.group(1)) if match else None


async def probe_icmp(host: str, timeout: float) -> ProbeResult:
    exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "PING.EXE")
    start = time.perf_counter()
    try:
        proc = await asyncio.create_subprocess_exec(
            exe, "-n", "1", "-w", str(max(1, int(timeout * 1000))), host,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return _fail("connect")
    try:
        async with asyncio.timeout(timeout + 1.0):
            stdout, _ = await proc.communicate()
    except BaseException as exc:  # includes cancellation: never leave ping.exe behind
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        if isinstance(exc, TimeoutError):
            return _fail("timeout")
        raise
    text = stdout.decode("ascii", errors="replace")
    if proc.returncode == 0 and "TTL=" in text:
        parsed = parse_ping_output(text)
        return ProbeResult(True, parsed if parsed is not None else _ms_since(start), None)
    return _fail("no_reply")


def listening_ports() -> dict[int, int]:
    """port -> pid of a LISTEN socket (blocking). pid 0 means "listening, owner unknown"."""
    ports: dict[int, int] = {}
    for conn in psutil.net_connections("tcp"):
        if conn.status != psutil.CONN_LISTEN or not conn.laddr:
            continue
        pid = conn.pid or 0
        if pid or conn.laddr.port not in ports:
            ports[conn.laddr.port] = pid
    return ports


def process_name(pid: int) -> str | None:
    try:
        return psutil.Process(pid).name()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return None


def _normalize_ip(text: str) -> str | None:
    try:
        return str(ipaddress.ip_address(text.split("%", 1)[0]))
    except ValueError:
        return None


def local_addresses() -> frozenset[str]:
    names = {"localhost", socket.gethostname().lower()}
    for addrs in psutil.net_if_addrs().values():
        for addr in addrs:
            if addr.family in (socket.AF_INET, socket.AF_INET6):
                ip = _normalize_ip(addr.address)
                if ip:
                    names.add(ip)
    return frozenset(names)


def is_local_host(host: str, local: frozenset[str]) -> bool:
    host = host.strip().lower().strip("[]")
    ip = _normalize_ip(host)
    if ip is not None:
        return ipaddress.ip_address(ip).is_loopback or ip in local
    return host in local


def classify(
    *,
    local: bool,
    port_known: bool,
    listening_pid: int | None,
    process_name: str | None,
    expected_process_name: str | None,
    probe_ok: bool,
    icmp_ok: bool | None,
) -> Issue | None:
    if local and port_known:
        if listening_pid is None:
            # No listener alone is not proof (the port snapshot can lag a fresh start): the probe must fail too.
            return None if probe_ok else Issue.PROCESS_DOWN
        if expected_process_name and process_name and process_name.lower() != expected_process_name.lower():
            return Issue.WRONG_PROCESS
        return None if probe_ok else Issue.UNRESPONSIVE
    if local:  # port lookup failed: judge by the probe alone, never PROCESS_DOWN
        return None if probe_ok else Issue.UNRESPONSIVE
    if probe_ok:
        return None
    return Issue.NETWORK_DOWN if icmp_ok is False else Issue.UNRESPONSIVE


class Prober:
    def __init__(self, clock: Clock, http: httpx.AsyncClient | None = None, timeout: float = PROBE_TIMEOUT_SEC) -> None:
        self._clock = clock
        self._timeout = timeout
        self._owns_http = http is None
        # trust_env=False: monitoring must not be routed through a system proxy.
        self._http = http if http is not None else httpx.AsyncClient(trust_env=False)
        self._ping = McpPingClient(self._http)
        self._urls: dict[int, str] = {}
        self._local = local_addresses()
        self._ports: dict[int, int] = {}
        self._ports_at: float | None = None
        self._ports_lock = asyncio.Lock()

    async def probe(self, mcp: Mcp) -> ProbeResult:
        config = mcp.config
        if config.probe == "tcp":
            return await probe_tcp(config.host, config.port, self._timeout)
        if config.probe == "icmp":
            return await probe_icmp(config.host, self._timeout)
        url = mcp.url
        previous = self._urls.get(mcp.id)
        if previous is not None and previous != url:  # endpoint edited: the old session is useless
            self._ping.forget(previous)
        self._urls[mcp.id] = url
        return await self._ping.ping(url, self._timeout)

    async def _port_snapshot(self) -> dict[int, int]:
        """Listening ports, shared by all MCPs for PORT_CACHE_TTL_SEC. Raises if the lookup fails."""
        async with self._ports_lock:
            now = time.monotonic()
            if self._ports_at is None or now - self._ports_at >= PORT_CACHE_TTL_SEC:
                self._ports = await asyncio.to_thread(listening_ports)
                self._ports_at = time.monotonic()
            return self._ports

    async def check(self, mcp: Mcp) -> CheckResult:
        config = mcp.config
        local = is_local_host(config.host, self._local)
        result = await self.probe(mcp)
        port_known, listening_pid, name = False, None, None
        errors = [] if result.ok or result.error is None else [result.error]
        if local:
            try:
                listening_pid = (await self._port_snapshot()).get(config.port)
                port_known = True
            except Exception as exc:  # reported in `error` so the monitor can log it (never swallowed silently)
                errors.append(f"port_lookup:{type(exc).__name__}")
            if listening_pid and config.expected_process_name:
                name = await asyncio.to_thread(process_name, listening_pid)
        icmp_ok: bool | None = None
        if not local and not result.ok:
            if config.probe == "icmp":
                icmp_ok = result.ok
            else:
                icmp_ok = (await probe_icmp(config.host, self._timeout)).ok
        issue = classify(
            local=local,
            port_known=port_known,
            listening_pid=listening_pid,
            process_name=name,
            expected_process_name=config.expected_process_name,
            probe_ok=result.ok,
            icmp_ok=icmp_ok,
        )
        return CheckResult(
            at=self._clock.now(),
            issue=issue,
            latency_ms=result.latency_ms,
            pid=listening_pid or None,
            process_name=name,
            error="; ".join(errors) or None,
        )

    def forget(self, mcp_id: int) -> None:
        url = self._urls.pop(mcp_id, None)
        if url is not None:
            self._ping.forget(url)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()
