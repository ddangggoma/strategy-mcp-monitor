"""Local-only, admin-only pre-notice message API (``edit_notice``): current text, versions, revert.

Every mutation that changes something is audited (``admin.audit``); failures with ``result="error"``,
denials by ``require``. Audit lines carry the version numbers plus a SHA-256 and the body length,
never the notice text. A save or revert that leaves the content unchanged writes nothing and is
not audited, because nothing changed.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, NoReturn

from fastapi import APIRouter, Depends, Path, Request
from pydantic import ValidationError

from app.auth.policy import Action
from app.clock import to_kst_iso
from app.notice.store import NoticeBody, NoticeNotFoundError, NoticeVersion, content_sha256
from app.services import Services
from app.users.store import User
from app.web.deps import ApiError, client_ip, get_channel, get_services, require
from app.web.mcp_shared import UserCache, cached_user_summary

router = APIRouter()

# Version 0 (the built-in text) is a valid target, so unlike script versions this starts at 0.
VersionNo = Annotated[int, Path(ge=0, le=2**63 - 1)]  # SQLite INTEGER range; larger overflows


def notice_json(
    services: Services, v: NoticeVersion, users: UserCache | None = None
) -> dict[str, Any]:
    return {
        "version": v.version,
        "title": v.content.title,
        "body": v.content.body,
        "button_text": v.content.button_text,
        "created_at": to_kst_iso(v.created_at) if v.created_at is not None else None,
        "author": cached_user_summary(services, v.author_id, users),
        "reverted_from": v.reverted_from,
    }


def _summary_json(services: Services, v: NoticeVersion, users: UserCache) -> dict[str, Any]:
    return {
        "version": v.version,
        "title": v.content.title,
        "created_at": to_kst_iso(v.created_at) if v.created_at is not None else None,
        "author": cached_user_summary(services, v.author_id, users),
        "reverted_from": v.reverted_from,
    }


def _audit(
    request: Request, services: Services, actor: User | None, action: str,
    result: Literal["ok", "error"],
    target: dict[str, Any],
) -> None:
    services.audit.admin(
        actor=actor, action=action, channel=get_channel(request), ip=client_ip(request),
        target=target, result=result,
    )


def _fail(
    request: Request, services: Services, actor: User | None, action: str, status: int, code: str,
    **target: Any,
) -> NoReturn:
    _audit(request, services, actor, action, "error", {**target, "error": code})
    raise ApiError(status, code)


@router.get("/api/notice")
async def get_notice(
    _user: User | None = Depends(require(Action.EDIT_NOTICE)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    return notice_json(services, services.notice.current())


@router.put("/api/notice")
async def put_notice(
    body: dict[str, Any],
    request: Request,
    actor: User | None = Depends(require(Action.EDIT_NOTICE)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    try:
        content = NoticeBody.model_validate(body).to_content()
    except ValidationError:
        _fail(request, services, actor, "notice_update", 422, "validation")
    previous = services.notice.current().version
    saved, created = services.notice.save(content, actor.id if actor else None)
    if created:
        _audit(request, services, actor, "notice_update", "ok", {
            "version": saved.version, "from_version": previous,
            "sha256": content_sha256(saved.content), "body_chars": len(saved.content.body),
        })
    return notice_json(services, saved)


@router.get("/api/notice/versions")
async def list_versions(
    _user: User | None = Depends(require(Action.EDIT_NOTICE)),
    services: Services = Depends(get_services),
) -> list[dict[str, Any]]:
    users: UserCache = {}
    return [_summary_json(services, v, users) for v in services.notice.versions()]


@router.get("/api/notice/versions/{version}")
async def get_version(
    version: VersionNo,
    _user: User | None = Depends(require(Action.EDIT_NOTICE)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    found = services.notice.version(version)
    if found is None:
        raise ApiError(404, "not_found")
    return notice_json(services, found)


@router.post("/api/notice/versions/{version}/revert")
async def revert_version(
    version: VersionNo,
    request: Request,
    actor: User | None = Depends(require(Action.EDIT_NOTICE)),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    try:
        reverted, created = services.notice.revert(version, actor.id if actor else None)
    except NoticeNotFoundError:
        _fail(request, services, actor, "notice_revert", 404, "not_found", from_version=version)
    if created:
        _audit(request, services, actor, "notice_revert", "ok", {
            "from_version": version, "version": reverted.version,
            "sha256": content_sha256(reverted.content), "body_chars": len(reverted.content.body),
        })
    return notice_json(services, reverted)
