from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.responses import FileResponse, JSONResponse, Response

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
IMMUTABLE = "public, max-age=31536000, immutable"
HTML_PAGES = {"board": "board.html", "admin": "admin.html", "notice": "notice.html"}

_CONTENT_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".json": "application/json",
    ".png": "image/png",
    ".ico": "image/x-icon",
}
_DEFAULT_CONTENT_TYPE = "application/octet-stream"
_CSP_TYPES = frozenset({"text/html; charset=utf-8", "image/svg+xml"})

# Characters that are separators, stream markers or wildcards on Windows (or control characters).
_BAD_PART_CHARS = re.compile(r'[\x00-\x1f\\:*?"<>|]')
# Device names Windows resolves to a device whatever the extension ("CON.txt" is still CON).
_RESERVED_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", "CLOCK$"}
    | {f"COM{n}" for n in "123456789¹²³"}
    | {f"LPT{n}" for n in "123456789¹²³"}
)
_NOT_FOUND = {"error": "not_found"}

AcceptEncoding = Annotated[str | None, Header()]


def _not_found() -> JSONResponse:
    return JSONResponse(_NOT_FOUND, status_code=404)


def safe_parts(raw: str) -> tuple[str, ...] | None:
    """Split a request path into plain file-name parts, or None when any part is suspicious.

    Rejects `..`, empty parts (`//`), absolute paths, backslashes, drive letters and NTFS
    alternate data streams (any `:`), wildcard/control characters, dot-files, names Windows
    would silently rewrite (trailing dot or space) and reserved device names.
    """
    if not raw or raw.startswith("/"):
        return None
    parts = PurePosixPath(raw).parts
    if "//" in raw or raw.endswith("/") or not parts:
        return None
    for part in parts:
        if part in (".", "..") or part.startswith(".") or part != part.rstrip(". "):
            return None
        if _BAD_PART_CHARS.search(part):
            return None
        if part.split(".", 1)[0].rstrip(" ").upper() in _RESERVED_DEVICES:
            return None
    return parts


def _accepted(accept_encoding: str | None) -> dict[str, float]:
    """Parse Accept-Encoding into {coding: q}; a malformed q counts as 0 (not acceptable)."""
    accepted: dict[str, float] = {}
    for item in (accept_encoding or "").split(","):
        coding, *params = (piece.strip() for piece in item.split(";"))
        if not coding:
            continue
        q = 1.0
        for param in params:
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    q = float(value.strip())
                except ValueError:
                    q = 0.0
        accepted[coding.lower()] = q
    return accepted


def pick_variant(path: Path, accept_encoding: str | None) -> tuple[Path, str | None]:
    """Choose the pre-compressed sibling to send: br, then gzip, else the file itself."""
    accepted = _accepted(accept_encoding)
    wildcard = accepted.get("*", 0.0)
    for coding, suffix in (("br", ".br"), ("gzip", ".gz")):
        if accepted.get(coding, wildcard) > 0:
            variant = path.with_name(path.name + suffix)
            if variant.is_file():
                return variant, coding
    return path, None


def _inside(root: Path, path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root)
    except (OSError, ValueError):
        return False


def static_router(dist: Path, *, notice: bool = True) -> APIRouter:
    """Routes for the built web app: pages, hashed /assets, favicon. `notice=False` drops /notice."""
    root = dist.resolve()
    router = APIRouter()

    def serve_file(parts: tuple[str, ...], accept_encoding: str | None, *, hashed: bool) -> Response:
        path = root.joinpath(*parts)
        if not _inside(root, path) or not path.is_file():
            return _not_found()
        chosen, encoding = pick_variant(path, accept_encoding)
        if encoding is not None and not _inside(root, chosen):
            chosen, encoding = path, None
        media_type = _CONTENT_TYPES.get(path.suffix.lower(), _DEFAULT_CONTENT_TYPE)
        headers = {
            "Cache-Control": IMMUTABLE if hashed else "no-cache",
            "Vary": "Accept-Encoding",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }
        if encoding is not None:
            headers["Content-Encoding"] = encoding
        if media_type in _CSP_TYPES:
            headers["Content-Security-Policy"] = CSP
        return FileResponse(chosen, media_type=media_type, headers=headers)

    @router.get("/")
    async def board(accept_encoding: AcceptEncoding = None) -> Response:
        return serve_file((HTML_PAGES["board"],), accept_encoding, hashed=False)

    @router.get("/admin")
    @router.get("/admin/{path:path}")  # SPA fallback: the client router resolves the rest
    async def admin(accept_encoding: AcceptEncoding = None) -> Response:
        return serve_file((HTML_PAGES["admin"],), accept_encoding, hashed=False)

    if notice:

        @router.get("/notice")
        async def notice_page(accept_encoding: AcceptEncoding = None) -> Response:
            return serve_file((HTML_PAGES["notice"],), accept_encoding, hashed=False)

    @router.get("/assets/{path:path}")
    async def asset(path: str, accept_encoding: AcceptEncoding = None) -> Response:
        parts = safe_parts(path)
        if parts is None:
            return _not_found()
        return serve_file(("assets", *parts), accept_encoding, hashed=True)

    @router.get("/favicon.svg")
    async def favicon(accept_encoding: AcceptEncoding = None) -> Response:
        return serve_file(("favicon.svg",), accept_encoding, hashed=False)

    return router
