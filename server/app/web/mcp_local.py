"""Local-only MCP routes: registration, deletion, ownership and script management.

Scripts run as SYSTEM, so none of this is registered on the external app. Every mutation is
audited (``admin.audit``), failures with ``result="error"``; denials are audited by ``require``.
Script bodies are never written to the audit log (only their version and sha256).
"""
from __future__ import annotations

import contextlib
from typing import Annotated, Any, Literal, NoReturn

from fastapi import APIRouter, Depends, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from app.auth.policy import Action, can
from app.clock import to_kst_iso
from app.monitor.engine import ActionInProgressError
from app.monitor.models import Mcp, McpConfig, ScriptKind
from app.monitor.scripts import (
    ScriptInfo,
    ScriptNotFoundError,
    ScriptRequiredError,
    ScriptUpload,
    ScriptValidationError,
    ScriptVersion,
)
from app.monitor.store import EndpointTakenError, McpNotFoundError, NameTakenError
from app.services import Services
from app.users.store import User
from app.web.channels import Channel
from app.web.deps import ApiError, client_ip, get_channel, get_services, require
from app.web.mcp_shared import McpId, mcp_detail

router = APIRouter()

MAX_ID = 2**63 - 1  # SQLite INTEGER range; larger values overflow
MAX_SCRIPT_CHARS = 65_536  # characters; the byte limit is enforced after encoding
VersionNo = Annotated[int, Path(ge=1, le=MAX_ID)]


# ---- request models ----------------------------------------------------------------


class ScriptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ext: Literal[".ps1", ".bat", ".cmd"]
    content: Annotated[str, Field(max_length=MAX_SCRIPT_CHARS)]

    def upload(self) -> ScriptUpload:
        return ScriptUpload(self.ext, self.content)


class CreateScripts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scripts: dict[ScriptKind, ScriptBody] = Field(default_factory=dict)


class OwnerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: Annotated[StrictInt, Field(ge=1, le=MAX_ID)]


# ---- helpers -----------------------------------------------------------------------


def mcp_owner(request: Request) -> int | None:
    """``require`` owner callback: the effective (active) owner of ``{mcp_id}``.

    ValueError (-> 422) for a malformed or out-of-range id; 404 for an unknown MCP.
    """
    raw = request.path_params["mcp_id"]
    if not (isinstance(raw, str) and raw.isascii() and raw.isdigit()):
        raise ValueError("mcp_id")
    mcp_id = int(raw)
    if not 1 <= mcp_id <= MAX_ID:
        raise ValueError("mcp_id")
    services = get_services(request)
    mcp = services.mcps.get(mcp_id)
    if mcp is None:
        raise ApiError(404, "not_found")
    return services.mcps.effective_owner_id(mcp)


class _Audit:
    """Audit context of one request: ``ok`` / ``fail`` write the ``admin.audit`` entry."""

    def __init__(self, request: Request, services: Services, actor: User | None, action: str) -> None:
        self._services = services
        self._actor = actor
        self._action = action
        self._ip = client_ip(request)
        self._channel: Channel = get_channel(request)

    def _write(self, target: dict[str, Any], result: Literal["ok", "error"]) -> None:
        self._services.audit.admin(
            actor=self._actor, action=self._action, channel=self._channel, ip=self._ip,
            target=target, result=result,
        )

    def ok(self, **target: Any) -> None:
        self._write(target, "ok")

    def fail(self, status: int, code: str, **target: Any) -> NoReturn:
        self._write({**target, "error": code}, "error")
        raise ApiError(status, code)

    def io_error(self, **target: Any) -> NoReturn:
        """A script file write failed (file held by antivirus or cmd, disk full): audit, then 500."""
        self._write({**target, "error": "io"}, "error")
        raise ApiError(500, "internal")


def _require_mcp(services: Services, mcp_id: int) -> Mcp:
    mcp = services.mcps.get(mcp_id)
    if mcp is None:
        raise ApiError(404, "not_found")
    return mcp


def _script_summary(info: ScriptInfo) -> dict[str, Any]:
    return {"kind": info.kind, "ext": info.ext, "version": info.version, "sha256": info.sha256}


def _version_json(v: ScriptVersion) -> dict[str, Any]:
    return {
        "version": v.version,
        "ext": v.ext,
        "sha256": v.sha256,
        "author_id": v.author_id,
        "created_at": to_kst_iso(v.created_at),
        "deleted": v.deleted,
    }


# ---- MCP create / delete / owner ---------------------------------------------------


@router.post("/api/mcps", status_code=201)
async def create_mcp(
    body: dict[str, Any],
    request: Request,
    actor: User | None = Depends(require(Action.CREATE_MCP)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    assert actor is not None  # require() denies anonymous
    audit = _Audit(request, services, actor, "mcp_create")
    config_part = {k: v for k, v in body.items() if k != "scripts"}
    try:
        config = McpConfig.model_validate(config_part)
        scripts = CreateScripts.model_validate({"scripts": body.get("scripts", {})}).scripts
    except ValidationError:
        audit.fail(422, "validation")
    try:
        mcp = services.scripts.create_mcp(
            config, actor.id, {kind: s.upload() for kind, s in scripts.items()}
        )
    except ScriptValidationError as exc:
        audit.fail(422, exc.code, name=config.name)
    except NameTakenError:
        audit.fail(409, "name_taken", name=config.name)
    except EndpointTakenError:
        audit.fail(409, "endpoint_taken", name=config.name)
    except OSError:
        audit.io_error(name=config.name)
    services.monitor.add(mcp)
    audit.ok(mcp_id=mcp.id, name=config.name, host=config.host, port=config.port)
    return mcp_detail(services, mcp)


@router.delete("/api/mcps/{mcp_id}", status_code=204)
async def delete_mcp(
    mcp_id: McpId,
    request: Request,
    actor: User | None = Depends(require(Action.DELETE_MCP, owner_id=mcp_owner)),
    services: Services = Depends(get_services),
) -> Response:
    audit = _Audit(request, services, actor, "mcp_delete")
    mcp = services.mcps.get(mcp_id)
    if mcp is None:
        audit.fail(404, "not_found", mcp_id=mcp_id)
    try:
        services.monitor.remove(mcp_id)  # refuses while a script runs; the stop script is NOT run
    except ActionInProgressError:
        audit.fail(409, "action_in_progress", mcp_id=mcp_id)
    try:
        services.mcps.delete(mcp_id)
    except McpNotFoundError:
        audit.fail(404, "not_found", mcp_id=mcp_id)
    except BaseException:
        with contextlib.suppress(ValueError):  # the row survived: keep monitoring it
            services.monitor.add(mcp)
        raise
    services.scripts.remove_dir(mcp_id)
    audit.ok(mcp_id=mcp_id, name=mcp.config.name)
    return Response(status_code=204)


@router.post("/api/mcps/{mcp_id}/owner")
async def transfer_owner(
    mcp_id: McpId,
    body: dict[str, Any],
    request: Request,
    actor: User | None = Depends(require(Action.TRANSFER_OWNERSHIP)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    audit = _Audit(request, services, actor, "mcp_owner_transfer")
    try:
        user_id = OwnerBody.model_validate(body).user_id
    except ValidationError:
        audit.fail(422, "validation", mcp_id=mcp_id)
    mcp = services.mcps.get(mcp_id)
    if mcp is None:
        audit.fail(404, "not_found", mcp_id=mcp_id)
    target = services.users.get(user_id)
    if target is None or not target.active:
        audit.fail(422, "invalid_owner", mcp_id=mcp_id)
    try:
        after = services.mcps.set_owner(mcp_id, target.id)
    except McpNotFoundError:
        audit.fail(404, "not_found", mcp_id=mcp_id)
    if services.monitor.engine(mcp_id) is not None:
        services.monitor.reconfigure(after)  # refresh the monitor's cached Mcp
    audit.ok(mcp_id=mcp_id, **{"from": mcp.owner_id, "to": target.id})
    return mcp_detail(services, after)


# ---- scripts: read -----------------------------------------------------------------


@router.get("/api/mcps/{mcp_id}/scripts")
async def list_scripts(
    mcp_id: McpId,
    _user: User | None = Depends(require(Action.VIEW_SCRIPTS)),
    services: Services = Depends(get_services),
) -> list[dict[str, Any]]:
    _require_mcp(services, mcp_id)
    return [
        {
            **_script_summary(i),
            "updated_at": to_kst_iso(i.updated_at),
            "updated_by": i.updated_by,
        }
        for i in services.scripts.list(mcp_id)
    ]


@router.get("/api/mcps/{mcp_id}/scripts/{kind}")
async def get_script(
    mcp_id: McpId,
    kind: ScriptKind,
    user: User | None = Depends(require(Action.VIEW_SCRIPTS)),
    services: Services = Depends(get_services),
    channel: Channel = Depends(get_channel),
) -> dict[str, Any]:
    mcp = _require_mcp(services, mcp_id)
    info = services.scripts.get(mcp_id, kind)
    content = services.scripts.content(mcp_id, kind)
    if info is None or content is None:
        raise ApiError(404, "not_found")
    owner = services.mcps.effective_owner_id(mcp)
    return {
        **_script_summary(info),
        "content": content,
        "editable": can(user, Action.EDIT_SCRIPTS, channel, owner),
    }


@router.get("/api/mcps/{mcp_id}/scripts/{kind}/versions")
async def list_versions(
    mcp_id: McpId,
    kind: ScriptKind,
    _user: User | None = Depends(require(Action.VIEW_SCRIPTS)),
    services: Services = Depends(get_services),
) -> list[dict[str, Any]]:
    _require_mcp(services, mcp_id)
    return [_version_json(v) for v in services.scripts.versions(mcp_id, kind)]


@router.get("/api/mcps/{mcp_id}/scripts/{kind}/versions/{version}")
async def get_version(
    mcp_id: McpId,
    kind: ScriptKind,
    version: VersionNo,
    _user: User | None = Depends(require(Action.VIEW_SCRIPTS)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    _require_mcp(services, mcp_id)
    found = services.scripts.version(mcp_id, kind, version)
    if found is None:
        raise ApiError(404, "not_found")
    return {**_version_json(found), "content": found.content}


# ---- scripts: edit (owner only) ----------------------------------------------------


@router.put("/api/mcps/{mcp_id}/scripts/{kind}")
async def put_script(
    mcp_id: McpId,
    kind: ScriptKind,
    body: dict[str, Any],
    request: Request,
    actor: User | None = Depends(require(Action.EDIT_SCRIPTS, owner_id=mcp_owner)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    assert actor is not None
    audit = _Audit(request, services, actor, "script_update")
    try:
        upload = ScriptBody.model_validate(body).upload()
    except ValidationError:
        audit.fail(422, "validation", mcp_id=mcp_id, kind=kind)
    try:
        info = services.scripts.put(mcp_id, kind, upload, actor.id)
    except ScriptValidationError as exc:
        audit.fail(422, exc.code, mcp_id=mcp_id, kind=kind)
    except McpNotFoundError:
        audit.fail(404, "not_found", mcp_id=mcp_id, kind=kind)
    except OSError:
        audit.io_error(mcp_id=mcp_id, kind=kind)
    audit.ok(mcp_id=mcp_id, kind=kind, version=info.version, sha256=info.sha256)
    return _script_summary(info)


@router.delete("/api/mcps/{mcp_id}/scripts/{kind}", status_code=204)
async def delete_script(
    mcp_id: McpId,
    kind: ScriptKind,
    request: Request,
    actor: User | None = Depends(require(Action.EDIT_SCRIPTS, owner_id=mcp_owner)),
    services: Services = Depends(get_services),
) -> Response:
    assert actor is not None
    audit = _Audit(request, services, actor, "script_delete")
    try:
        services.scripts.delete(mcp_id, kind, actor.id)
    except ScriptRequiredError:
        audit.fail(409, "script_required", mcp_id=mcp_id, kind=kind)
    except ScriptNotFoundError:
        audit.fail(404, "not_found", mcp_id=mcp_id, kind=kind)
    audit.ok(mcp_id=mcp_id, kind=kind)
    return Response(status_code=204)


@router.post("/api/mcps/{mcp_id}/scripts/{kind}/versions/{version}/revert")
async def revert_script(
    mcp_id: McpId,
    kind: ScriptKind,
    version: VersionNo,
    request: Request,
    actor: User | None = Depends(require(Action.EDIT_SCRIPTS, owner_id=mcp_owner)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    assert actor is not None
    audit = _Audit(request, services, actor, "script_revert")
    try:
        info = services.scripts.revert(mcp_id, kind, version, actor.id)
    except ScriptNotFoundError:
        audit.fail(404, "not_found", mcp_id=mcp_id, kind=kind, from_version=version)
    except ScriptValidationError as exc:
        audit.fail(422, exc.code, mcp_id=mcp_id, kind=kind, from_version=version)
    except OSError:
        audit.io_error(mcp_id=mcp_id, kind=kind, from_version=version)
    audit.ok(mcp_id=mcp_id, kind=kind, from_version=version, version=info.version)
    return _script_summary(info)
