from __future__ import annotations

import asyncio
import contextlib
import errno
import logging
import signal
import socket
import sys
import threading
from collections.abc import Awaitable, Callable, Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import uvicorn
from fastapi import FastAPI

from app.collect.config import CollectorConfig
from app.rootlock import RootLock
from app.services import Services, build_services
from app.web.app_factory import create_app

if TYPE_CHECKING:
    from app.winsvc.start_type import ServiceConfigurator


def server_configs(
    local_app: FastAPI,
    external_app: FastAPI,
    local_port: int = 8700,
    external_port: int = 8701,
    external_host: str = "0.0.0.0",
) -> list[uvicorn.Config]:
    # proxy_headers=False: no reverse proxy by design, so X-Forwarded-For must never
    # override request.client.host (audit ip, OTP per-IP limit).
    common: dict[str, Any] = {"log_level": "info", "proxy_headers": False, "timeout_graceful_shutdown": 10}
    return [
        uvicorn.Config(local_app, host="127.0.0.1", port=local_port, **common),
        uvicorn.Config(external_app, host=external_host, port=external_port, **common),
    ]


_ADDRESS_TAKEN = frozenset(
    e for e in (errno.EADDRINUSE, errno.EACCES, getattr(errno, "WSAEADDRINUSE", None),
                getattr(errno, "WSAEACCES", None)) if e is not None
)


class PortInUseError(OSError):
    """A channel's port is taken (or bound exclusively by another process): exit code 3 (W23)."""

    def __init__(self, host: str, port: int) -> None:
        super().__init__(f"port {port} is already in use ({host})")
        self.host = host
        self.port = port


def bind_listener(host: str, port: int, backlog: int = 2048) -> socket.socket:
    """A listening socket for ``host:port``, bound now.

    Exclusive on Windows (``SO_EXCLUSIVEADDRUSE``): no other process can bind the same address
    while we hold it, which uvicorn's own ``SO_REUSEADDR`` bind would allow (I1, W23). A port in
    use (or refused for access) raises :class:`PortInUseError`; other ``OSError``s (an address
    this machine does not have) pass through unchanged."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        else:  # pragma: no cover - not Windows
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as exc:
            if exc.errno in _ADDRESS_TAKEN or getattr(exc, "winerror", None) in (10048, 10013):
                raise PortInUseError(host, port) from exc
            raise
        sock.listen(backlog)
    except BaseException:
        sock.close()
        raise
    return sock


def bind_listeners(addresses: Sequence[tuple[str, int]]) -> list[socket.socket]:
    """Both channels' sockets, bound before anything else starts: connections made meanwhile wait
    in the backlog. All or nothing."""
    sockets: list[socket.socket] = []
    try:
        for host, port in addresses:
            sockets.append(bind_listener(host, port))
    except BaseException:
        for sock in sockets:
            sock.close()
        raise
    for sock in sockets:
        host, port = sock.getsockname()[:2]
        logging.getLogger("uvicorn.error").info("Uvicorn running on http://%s:%d", host, port)
    return sockets


class _Server(uvicorn.Server):
    """uvicorn.Server that leaves signal handling to serve(), so two servers share one handler;
    ``on_started`` runs once it accepts connections."""

    def __init__(self, config: uvicorn.Config, on_started: Callable[[], None] | None = None) -> None:
        super().__init__(config)
        self._on_started = on_started

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if self.started and self._on_started is not None:
            self._on_started()


def request_exit(servers: Sequence[uvicorn.Server]) -> None:
    """First signal: graceful exit. A repeated signal: force exit (mirrors uvicorn's own handler)."""
    for server in servers:
        if server.should_exit:
            server.force_exit = True
        else:
            server.should_exit = True


class ShutdownSequence:
    """The service stop, in order: first ``before_exit`` (the collectors' stop: the agent
    supervisor tells each session agent to exit, and the agent closes its notice window), and only
    then the servers. The agents hear ``exit`` over the Local channel, so it must still answer.

    ``request()`` (loop thread): the first call starts that sequence; a repeated call goes to
    ``request_exit`` (stop serving now, then force), so an impatient second Ctrl+C still works.
    """

    def __init__(self, servers: Sequence[Any], before_exit: Callable[[], Awaitable[None]]) -> None:
        self._servers = servers
        self._before_exit = before_exit
        self._task: asyncio.Task[None] | None = None

    def request(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run(), name="shutdown")
        else:
            request_exit(self._servers)

    async def _run(self) -> None:
        try:
            await self._before_exit()
        finally:
            for server in self._servers:  # graceful only: a repeated request may already have forced
                server.should_exit = True

    async def wait(self) -> None:
        """Until a started sequence is done (re-raises its error); at once when none started."""
        if self._task is not None:
            await self._task


@contextlib.contextmanager
def _stop_on_signals(on_signal: Callable[[], None]) -> Iterator[None]:
    """Ctrl+C / SIGTERM / SIGBREAK call ``on_signal`` on the loop thread."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    loop = asyncio.get_running_loop()

    def _handler(signum, frame) -> None:  # noqa: ARG001
        loop.call_soon_threadsafe(on_signal)

    sigs = [s for s in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None)) if s]
    original = {s: signal.signal(s, _handler) for s in sigs}
    try:
        yield
    finally:
        for s, h in original.items():
            signal.signal(s, h)


class ServeControl:
    """Controls a running ``serve()`` from other threads (the Windows service's SCM handler).

    ``request_stop()`` goes through the same ``ShutdownSequence`` as Ctrl+C (collectors first,
    while the Local channel still answers; F01). A stop requested before the servers exist stops
    them right after they start. Every method is thread-safe and may be called repeatedly.
    ``configurator`` (as a service) replaces the real SCM for the start-type reconcile.
    """

    def __init__(self, *, as_service: bool = False, configurator: ServiceConfigurator | None = None) -> None:
        self.as_service = as_service
        self.configurator = configurator
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown: ShutdownSequence | None = None
        self._nudge: Callable[[], None] | None = None
        self._stop_requested = False
        self._started = threading.Event()
        self._stopped = threading.Event()

    def request_stop(self) -> None:
        with self._lock:
            if self._stop_requested:
                return  # a repeated SCM stop must not turn into a forced exit
            self._stop_requested = True
            loop, shutdown = self._loop, self._shutdown
        if loop is not None and shutdown is not None:
            with contextlib.suppress(RuntimeError):  # the loop has already closed
                loop.call_soon_threadsafe(shutdown.request)

    def nudge_sessions(self) -> None:
        """Poll the RDP sessions now; a no-op without session collection or before it starts."""
        with self._lock:
            nudge = self._nudge
        if nudge is not None:
            nudge()

    def wait_started(self, timeout: float | None = None) -> bool:
        """Until both servers accept connections."""
        return self._started.wait(timeout)

    def wait_stopped(self, timeout: float | None = None) -> bool:
        """Until ``serve()`` has returned (or failed)."""
        return self._stopped.wait(timeout)

    # serve() side, on the loop thread
    def _attach(
        self, loop: asyncio.AbstractEventLoop, shutdown: ShutdownSequence, nudge: Callable[[], None]
    ) -> None:
        with self._lock:
            self._loop, self._shutdown, self._nudge = loop, shutdown, nudge
            stop_now = self._stop_requested
        if stop_now:
            loop.call_soon(shutdown.request)

    def _detach(self) -> None:
        with self._lock:
            self._loop = None
            self._shutdown = None
            self._nudge = None

    def _set_started(self) -> None:
        self._started.set()

    def _set_stopped(self) -> None:
        self._stopped.set()


async def serve(
    root: Path,
    local_port: int = 8700,
    external_port: int = 8701,
    *,
    external_host: str = "0.0.0.0",
    static_dir: Path | None = None,
    dev_otp_code: str | None = None,
    collectors: CollectorConfig | None = None,
    control: ServeControl | None = None,
    kill_scripts_on_stop: bool = True,
) -> None:
    """Run both channels until a signal or ``control.request_stop()``.

    Start: both ports (``PortInUseError``, before the root is touched) → ``RootLock``
    (``RootInUseError``) → ``build_services`` (``DatabaseTooNewError``) → log writer → log index →
    retention job → monitor → collectors → (as a service: start-type reconcile) → servers.
    Stop: ``ShutdownSequence`` (collectors, then servers) → monitor (killing abandoned script
    trees when ``kill_scripts_on_stop``, W21) → retention → index → log → DB → ports → root lock.
    """
    try:
        root = Path(root).resolve()
        if dev_otp_code is not None:
            print("WARNING: dev OTP code enabled", file=sys.stderr, flush=True)
        if static_dir is not None and not (static_dir / "board.html").is_file():
            print(f"WARNING: no built web app in {static_dir}; serving the API only", file=sys.stderr, flush=True)
        # I1/W23: own both ports first, so a session agent launched by the supervisor never finds
        # the Local port unbound (or bound by another process), and a busy port changes nothing.
        sockets = bind_listeners([("127.0.0.1", local_port), (external_host, external_port)])
        try:
            with RootLock(root):
                services = build_services(root, dev_fixed_code=dev_otp_code, collectors=collectors)
                await _serve_built(
                    services, sockets, local_port, external_port, external_host, static_dir,
                    control, kill_scripts_on_stop,
                )
        finally:
            for sock in sockets:
                sock.close()
    finally:
        if control is not None:
            control._set_stopped()


async def _serve_built(
    services: Services,
    sockets: Sequence[socket.socket],
    local_port: int,
    external_port: int,
    external_host: str,
    static_dir: Path | None,
    control: ServeControl | None,
    kill_scripts_on_stop: bool,
) -> None:
    """``serve()`` once the ports, the root lock and the services are ours."""
    try:
        local_url = f"http://127.0.0.1:{local_port}"
        services.agents.configure(local_url)
        if services.agent_supervisor is not None:
            services.agent_supervisor.configure(local_url)
        configs = server_configs(
            create_app("local", services, static_dir),
            create_app("external", services, static_dir),
            local_port,
            external_port,
            external_host,
        )
    except BaseException:
        services.db.close()
        raise
    await services.log.start()
    try:
        await services.log_index.start()
        try:
            await services.retention.start()
            try:
                await _serve_started(services, configs, sockets, control, kill_scripts_on_stop)
            finally:
                await services.retention.stop()  # first of the stops below: it uses the index and the DB
        finally:
            await services.log_index.stop()
    finally:
        await services.log.stop()
        services.db.close()


async def _serve_started(
    services: Services,
    configs: Sequence[uvicorn.Config],
    sockets: Sequence[socket.socket],
    control: ServeControl | None,
    kill_scripts_on_stop: bool,
) -> None:
    """``serve()`` once the log writer, the log index and the retention job run: monitor,
    collectors, servers."""
    await services.monitor.start()
    try:
        await services.collectors.start()
        shutdown: ShutdownSequence | None = None
        try:
            if control is not None and control.as_service:
                services.start_type.running_as_service = True
                if control.configurator is not None:
                    services.start_type.configurator = control.configurator
                desired = services.settings.get().service_start_type  # config.db: on the loop thread
                await asyncio.to_thread(services.start_type.reconcile, desired)
            waiting = len(configs)

            def one_started() -> None:
                nonlocal waiting
                waiting -= 1
                if waiting == 0 and control is not None:
                    control._set_started()

            servers = [_Server(cfg, one_started) for cfg in configs]

            async def before_exit() -> None:
                # What is queued reaches the disk before the slow stops (plan review I5): a stop the
                # OS cuts short (shutdown) still leaves the trail up to here.
                await services.log.flush()
                await services.collectors.stop()
                await services.log.flush()

            shutdown = ShutdownSequence(servers, before_exit)
            if control is not None:
                control._attach(asyncio.get_running_loop(), shutdown, services.collectors.nudge_sessions)
            try:
                with _stop_on_signals(shutdown.request):
                    await asyncio.gather(
                        *(s.serve(sockets=[sock]) for s, sock in zip(servers, sockets, strict=True))
                    )
            finally:
                if control is not None:
                    control._detach()
        finally:
            try:
                if shutdown is not None:
                    await shutdown.wait()
            finally:
                await services.collectors.stop()  # a no-op after the sequence stopped them
    finally:
        await services.monitor.stop(kill_abandoned=kill_scripts_on_stop)
        await services.log.flush()  # monitor.stop{killed} before the retention and index stops
