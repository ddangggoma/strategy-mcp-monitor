"""``python -m app seed-demo``: DEV/TEST ONLY demo data for a test install.

Creates three demo users and the three dummy MCPs of ``dummy-mcps/`` (with start/stop/restart
wrapper scripts that run ``dummy-mcps/examples/*.ps1``) through the real stores, so every value
passes the same validation as the API, and appends one ``admin.audit`` line per creation with
``actor: "seed-demo"``. Idempotent: a user (by email) or MCP (by name) that already exists is left
exactly as it is. The caller holds the data root lock (the service must be stopped).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.clock import Clock, to_kst_iso
from app.db import Database
from app.logstore.writer import DailyJsonlWriter
from app.monitor.models import McpConfig
from app.monitor.scripts import SCRIPT_KINDS, ScriptStore, ScriptUpload, ScriptValidationError
from app.monitor.store import EndpointTakenError, McpStore, NameTakenError
from app.paths import AppPaths
from app.users.store import Role, User, UserExistsError, UserStore

ACTOR = "seed-demo"
DEMO_HOST = "127.0.0.1"
RUN_DIR_NAME = "demo-run"


@dataclass(frozen=True)
class DemoUser:
    email: str
    name: str
    role: Role


@dataclass(frozen=True)
class DemoMcp:
    name: str  # also the dummy-mcps MCP_NAME (examples/start.ps1 maps it to the module)
    module: str  # the dummy-mcps package run with ``python -m``
    port: int  # its default port (dummy-mcps/<module>/__main__.py)
    owner_email: str


DEMO_USERS: tuple[DemoUser, ...] = (
    DemoUser("dev1@example.com", "개발자 1", "developer"),
    DemoUser("dev2@example.com", "개발자 2", "developer"),
    DemoUser("ops@example.com", "운영 관리자", "admin"),
)

DEMO_MCPS: tuple[DemoMcp, ...] = (
    DemoMcp("seoul-weather", "seoul_weather", 9101, "dev1@example.com"),
    DemoMcp("calculator", "calculator", 9102, "dev2@example.com"),
    DemoMcp("seoul-clock", "seoul_clock", 9103, "dev1@example.com"),
)


class DemoSetupError(ValueError):
    """A bad argument (dummy-mcps folder, owner email): nothing was changed."""


@dataclass
class SeedReport:
    users_created: list[str] = field(default_factory=list)
    users_existing: list[str] = field(default_factory=list)
    mcps_created: list[str] = field(default_factory=list)
    mcps_existing: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def check_dummy_dir(dummy_dir: Path) -> Path:
    """The absolute dummy-mcps folder, after checking it has the example scripts and packages."""
    resolved = dummy_dir.resolve()
    if any(c in str(resolved) for c in "\r\n\0"):
        raise DemoSetupError(f"invalid dummy-mcps path: {resolved!r}")
    missing = [
        rel
        for rel in (
            *(Path("examples") / f"{kind}.ps1" for kind in SCRIPT_KINDS),
            *(Path(m.module) / "__main__.py" for m in DEMO_MCPS),
        )
        if not (resolved / rel).is_file()
    ]
    if missing:
        names = ", ".join(str(p) for p in missing)
        raise DemoSetupError(f"{resolved} is not a dummy-mcps folder (missing {names})")
    return resolved


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def wrapper_script(kind: str, dummy_dir: Path, run_dir: Path) -> str:
    """A ``.ps1`` that runs ``dummy-mcps/examples/<kind>.ps1`` with its environment set.

    The monitor runs scripts as SYSTEM with MCP_ID/MCP_NAME/MCP_HOST/MCP_PORT set; the example
    also needs DUMMY_MCPS_DIR, and DUMMY_MCP_RUN_DIR keeps its pid and log files under the data
    root instead of the checkout.
    """
    example = dummy_dir / "examples" / f"{kind}.ps1"
    return "\n".join(
        (
            f"# MCP Monitor demo (seed-demo, test only): {kind} a dummy MCP via dummy-mcps/examples/{kind}.ps1.",
            f"$env:DUMMY_MCPS_DIR = {_ps_quote(str(dummy_dir))}",
            f"$env:DUMMY_MCP_RUN_DIR = {_ps_quote(str(run_dir))}",
            f"& {_ps_quote(str(example))}",
            "exit $LASTEXITCODE",
            "",
        )
    )


class _Audit:
    """``admin.audit`` lines (actor ``seed-demo``) appended to today's JSONL file at the end."""

    def __init__(self, paths: AppPaths, clock: Clock) -> None:
        self._writer = DailyJsonlWriter(paths.logs_dir)
        self._clock = clock
        self._events: list[dict[str, Any]] = []

    def add(self, action: str, target: dict[str, Any], result: Literal["ok", "error"]) -> None:
        self._events.append(
            {
                "ts": to_kst_iso(self._clock.now()),
                "cat": "admin.audit",
                "actor": ACTOR,
                "actor_id": None,
                "actor_email": None,
                "action": action,
                "channel": "local",
                "ip": None,
                "target": target,
                "result": result,
            }
        )

    def flush(self) -> None:
        if self._events:
            self._writer.write_batch(self._events)
            self._events = []


def _creator(users: UserStore, owner_email: str | None) -> int | None:
    """The admin recorded as ``created_by`` of the demo users (default: the first active admin)."""
    if owner_email is not None:
        owner = users.get_by_email(owner_email)
        if owner is None or owner.role != "admin" or not owner.active:
            raise DemoSetupError(f"--owner-email {owner_email} is not an active admin")
        return owner.id
    admins = [u for u in users.list() if u.role == "admin" and u.active]
    return admins[0].id if admins else None


def seed(
    root: Path,
    db: Database,
    clock: Clock,
    dummy_dir: Path,
    owner_email: str | None = None,
    *,
    say: Callable[[str], None] = print,
) -> SeedReport:
    """Create what is missing; ``db`` is migrated and the root lock is held by the caller."""
    paths = AppPaths(root)
    dummy_dir = check_dummy_dir(dummy_dir)
    run_dir = paths.data_dir / RUN_DIR_NAME
    users = UserStore(db, clock)
    mcps = McpStore(db, clock, users)
    scripts = ScriptStore(db, paths, clock, mcps)
    created_by = _creator(users, owner_email)
    audit = _Audit(paths, clock)
    report = SeedReport()
    try:
        by_email: dict[str, User] = {}
        for demo in DEMO_USERS:
            existing = users.get_by_email(demo.email)
            if existing is not None:
                by_email[demo.email] = existing
                report.users_existing.append(demo.email)
                continue
            try:
                user = users.create(demo.email, demo.name, demo.role, created_by=created_by)
            except UserExistsError:  # created meanwhile: cannot happen under the root lock
                report.failures.append(f"user {demo.email}: exists")
                continue
            by_email[demo.email] = user
            report.users_created.append(demo.email)
            audit.add("user_create", {"user_id": user.id, "email": user.email, "role": user.role}, "ok")

        existing_names = {m.config.name.lower() for m in mcps.list()}
        for demo_mcp in DEMO_MCPS:
            if demo_mcp.name.lower() in existing_names:
                report.mcps_existing.append(demo_mcp.name)
                continue
            owner = by_email.get(demo_mcp.owner_email)
            if owner is None:
                report.failures.append(f"MCP {demo_mcp.name}: owner {demo_mcp.owner_email} missing")
                continue
            config = McpConfig.model_validate(
                {
                    "name": demo_mcp.name,
                    "host": DEMO_HOST,
                    "port": demo_mcp.port,
                    "path": "/mcp",
                    "probe": "mcp_ping",
                    "autostart_on_boot": True,
                }
            )
            uploads = {
                kind: ScriptUpload(".ps1", wrapper_script(kind, dummy_dir, run_dir)) for kind in SCRIPT_KINDS
            }
            target: dict[str, Any] = {"name": config.name}
            try:
                mcp = scripts.create_mcp(config, owner.id, uploads)
            except (NameTakenError, EndpointTakenError, ScriptValidationError, OSError) as exc:
                code = {
                    NameTakenError: "name_taken",
                    EndpointTakenError: "endpoint_taken",
                }.get(type(exc), getattr(exc, "code", "io"))
                report.failures.append(f"MCP {demo_mcp.name}: {code}")
                audit.add("mcp_create", {**target, "error": code}, "error")
                continue
            report.mcps_created.append(demo_mcp.name)
            audit.add(
                "mcp_create",
                {**target, "mcp_id": mcp.id, "host": config.host, "port": config.port, "owner_id": owner.id},
                "ok",
            )
    finally:
        audit.flush()
    _summary(report, root, dummy_dir, run_dir, say)
    return report


def _summary(report: SeedReport, root: Path, dummy_dir: Path, run_dir: Path, say: Callable[[str], None]) -> None:
    say(f"데모 데이터(seed-demo, 테스트 전용): {root}")
    for demo in DEMO_USERS:
        state = "만듦" if demo.email in report.users_created else "이미 있음"
        if demo.email in report.users_created or demo.email in report.users_existing:
            say(f"  사용자 {demo.email} ({demo.name}, {demo.role}): {state}")
    for demo_mcp in DEMO_MCPS:
        if demo_mcp.name in report.mcps_created or demo_mcp.name in report.mcps_existing:
            state = "만듦" if demo_mcp.name in report.mcps_created else "이미 있음(바꾸지 않음)"
            say(
                f"  MCP {demo_mcp.name} {DEMO_HOST}:{demo_mcp.port} (담당 {demo_mcp.owner_email}): {state}"
            )
    say(f"  스크립트: {dummy_dir}\\examples\\{{start,stop,restart}}.ps1 실행, 실행 파일은 {run_dir}")
    for failure in report.failures:
        say(f"  실패: {failure}")
