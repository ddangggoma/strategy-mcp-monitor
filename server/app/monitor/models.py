from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class McpState(StrEnum):
    HEALTHY = "HEALTHY"
    SUSPECT = "SUSPECT"
    ACTION = "ACTION"
    RECOVERING = "RECOVERING"
    FAILED = "FAILED"
    MAINTENANCE = "MAINTENANCE"


class Issue(StrEnum):
    PROCESS_DOWN = "PROCESS_DOWN"
    UNRESPONSIVE = "UNRESPONSIVE"
    NETWORK_DOWN = "NETWORK_DOWN"
    WRONG_PROCESS = "WRONG_PROCESS"


ALERT_ONLY_ISSUES = frozenset({Issue.NETWORK_DOWN, Issue.WRONG_PROCESS})

ProbeKind = Literal["mcp_ping", "tcp", "icmp"]
ScriptKind = Literal["start", "stop", "restart"]
ActionKind = ScriptKind
Trigger = Literal["auto", "manual", "boot"]
ScriptStatus = Literal["ok", "failed", "timeout", "error"]

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)


def _normalize_host(value: str) -> str:
    host = value.strip().lower()
    if "%" not in host:  # a zone id ("fe80::1%eth0") is not a valid URL host
        try:
            return str(ipaddress.ip_address(host))  # canonical form: "0:0::1" == "::1"
        except ValueError:
            pass
    # A host whose last label is all digits is a malformed IPv4 literal ("999.1.1.1", "1.2.3"),
    # not a hostname: resolvers would read it as an obscure numeric address.
    if _HOSTNAME_RE.fullmatch(host) and not host.rsplit(".", 1)[-1].isdigit():
        return host
    raise ValueError("host must be a hostname, IPv4 or IPv6 address")


# C0 controls, DEL and C1 controls: never valid in a name a script or a log line receives.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# The name reaches scripts as MCP_NAME. cmd expands %MCP_NAME% before it parses the line, so these
# characters would inject commands into a .bat/.cmd (& | < > ^ " and % ! for nested expansion);
# the backtick is PowerShell's escape character.
_NAME_FORBIDDEN_RE = re.compile(r"[\x00-\x1f\x7f-\x9f%^&|<>\"!`]")


def _check_name(value: str) -> str:
    if _NAME_FORBIDDEN_RE.search(value):
        raise ValueError('name must not contain control characters or any of % ^ & | < > " ! `')
    return value


def _check_process_name(value: str | None) -> str | None:
    if value is not None and _CONTROL_RE.search(value):
        raise ValueError("expected_process_name must not contain control characters")
    return value


class McpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: Annotated[str, Field(min_length=1, max_length=64)]
    host: str
    port: Annotated[int, Field(ge=1, le=65535)]
    path: Annotated[str, Field(max_length=200, pattern=r"^/\S*$")] = "/mcp"
    probe: ProbeKind = "mcp_ping"
    expected_process_name: Annotated[str, Field(min_length=1, max_length=260)] | None = None
    action_delay_sec: Annotated[int, Field(ge=1, le=3600)] = 30
    startup_grace_sec: Annotated[int, Field(ge=0, le=600)] = 30
    max_auto_actions: Annotated[int, Field(ge=1, le=20)] = 3
    window_sec: Annotated[int, Field(ge=60, le=86400)] = 600
    auto_recovery: bool = True
    autostart_on_boot: bool = False
    maintenance: bool = False
    script_timeout_sec: Annotated[int, Field(ge=10, le=120)] = 120

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @field_validator("name")
    @classmethod
    def _safe_name(cls, v: str) -> str:
        return _check_name(v)

    @field_validator("expected_process_name")
    @classmethod
    def _safe_process_name(cls, v: str | None) -> str | None:
        return _check_process_name(v)

    @field_validator("host", mode="before")
    @classmethod
    def _check_host(cls, v: object) -> object:
        return _normalize_host(v) if isinstance(v, str) else v  # non-str: strict mode rejects


@dataclass(frozen=True)
class Mcp:
    id: int
    config: McpConfig
    owner_id: int | None
    created_by: int | None
    created_at: datetime
    # Set when the stored config fails validation (e.g. a row written before a validator tightened).
    # ``config`` then holds the stored values unvalidated: such an MCP is never monitored or run,
    # it is only listed so an admin can fix (PUT) or delete it.
    config_error: str | None = None

    @property
    def url(self) -> str:
        host = self.config.host
        if ":" in host:  # IPv6 literal
            host = f"[{host}]"
        return f"http://{host}:{self.config.port}{self.config.path}"


@dataclass(frozen=True)
class CheckResult:
    at: datetime
    issue: Issue | None
    latency_ms: float | None
    pid: int | None
    process_name: str | None
    error: str | None
