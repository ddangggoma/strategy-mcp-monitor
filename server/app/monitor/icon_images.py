"""The per-MCP icon image: the MCP's own logo, uploaded by whoever may edit its settings.

An uploaded image takes precedence over the emoji (``McpConfig.icon``) wherever the icon shows; the
emoji, then the default MCP icon, are the fallbacks. The bytes live in ``mcp_icons`` (migration 9,
one row per MCP, removed with the MCP) and are served as they were uploaded, under a canonical
Content-Type, with ``nosniff`` and a sandboxing CSP (app/web/mcp_shared.py).

What is accepted (``check_image``):
  - at most ``MAX_BYTES`` (256 KiB);
  - PNG, JPEG, WebP, GIF, ICO or SVG, and the bytes must be what the Content-Type claims (magic
    bytes; the sniffed canonical type is stored, e.g. image/vnd.microsoft.icon -> image/x-icon);
  - raster images ``MIN_PX``..``MAX_PX`` pixels on each side, read from the header (PNG IHDR, GIF
    logical screen, WebP VP8/VP8L/VP8X, JPEG SOFn, the largest ICO entry) - pixels are not decoded;
  - SVG: well-formed XML whose root is ``<svg>`` in the SVG namespace, with no DOCTYPE (so no
    entities), no processing instructions, no ``script``/``foreignObject``/HTML elements, no
    ``on*`` attributes, no animation that targets ``href``, and every ``href``/``xlink:href`` and
    CSS ``url(...)`` either a same-document ``#fragment`` or a ``data:image/(png|jpeg|webp|gif)``
    URI (no ``@import``). Browsers never run scripts or fetch resources for an SVG shown with
    ``<img>``; these rules also keep the file harmless when it is opened directly.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import struct
import xml.parsers.expat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.clock import Clock
from app.db import Database

MAX_BYTES = 256 * 1024
MIN_PX = 16
MAX_PX = 1024
VERSION_HEX = 12  # sha256 hex digits in the URL's ``v`` (cache busting)

PNG, JPEG, WEBP, GIF, ICO, SVG = (
    "image/png", "image/jpeg", "image/webp", "image/gif", "image/x-icon", "image/svg+xml",
)
# Accepted request Content-Types -> the canonical type stored and served.
ACCEPTED_TYPES: dict[str, str] = {
    PNG: PNG, JPEG: JPEG, WEBP: WEBP, GIF: GIF, ICO: ICO, "image/vnd.microsoft.icon": ICO, SVG: SVG,
}

_SVG_NS = "http://www.w3.org/2000/svg"
_XHTML_NS = "http://www.w3.org/1999/xhtml"
_FORBIDDEN_ELEMENTS = frozenset({"script", "foreignobject", "iframe", "embed", "object", "handler"})
_ANIMATIONS = frozenset({"set", "animate", "animatemotion", "animatetransform", "animatecolor"})
_DATA_IMAGE = re.compile(r"data:image/(?:png|jpeg|webp|gif)[;,]", re.IGNORECASE)
_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)


class IconImageError(Exception):
    """Refused upload; ``status`` / ``code`` are the HTTP answer (413 body_too_large, 422 validation)."""

    def __init__(self, reason: str, status: int = 422, code: str = "validation") -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.code = code


def _invalid(reason: str) -> IconImageError:
    return IconImageError(reason)


# ---- type sniffing + raster dimensions ----------------------------------------------


def sniff(data: bytes) -> str | None:
    """The canonical image type the bytes start like, or None. SVG is the text fallback."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return GIF
    if data[:4] == b"\x00\x00\x01\x00":
        return ICO
    head = data[:512].lstrip(b"\xef\xbb\xbf").lstrip()
    if head.startswith(b"<"):
        return SVG
    return None


def _png_size(d: bytes) -> tuple[int, int]:
    if len(d) < 24 or d[12:16] != b"IHDR":
        raise _invalid("png: no IHDR")
    w, h = struct.unpack(">II", d[16:24])
    return w, h


def _gif_size(d: bytes) -> tuple[int, int]:
    if len(d) < 10:
        raise _invalid("gif: truncated")
    w, h = struct.unpack("<HH", d[6:10])
    return w, h


def _webp_size(d: bytes) -> tuple[int, int]:
    chunk = d[12:16]
    if chunk == b"VP8 " and len(d) >= 30 and d[23:26] == b"\x9d\x01\x2a":
        w, h = struct.unpack("<HH", d[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if chunk == b"VP8L" and len(d) >= 25 and d[20] == 0x2F:
        bits = int.from_bytes(d[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X" and len(d) >= 30:
        return int.from_bytes(d[24:27], "little") + 1, int.from_bytes(d[27:30], "little") + 1
    raise _invalid("webp: unknown chunk")


# SOFn markers carry the frame size; C4 (DHT), C8 (JPG) and CC (DAC) share the range but are not frames.
_JPEG_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def _jpeg_size(d: bytes) -> tuple[int, int]:
    i = 2
    while i + 4 <= len(d):
        if d[i] != 0xFF:
            raise _invalid("jpeg: bad marker")
        marker = d[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # no length
            i += 2
            continue
        if marker in (0xD9, 0xDA):  # end of image / start of scan before any frame header
            break
        (length,) = struct.unpack(">H", d[i + 2:i + 4])
        if length < 2:
            raise _invalid("jpeg: bad segment")
        if marker in _JPEG_SOF:
            if i + 9 > len(d):
                break
            h, w = struct.unpack(">HH", d[i + 5:i + 9])
            return w, h
        i += 2 + length
    raise _invalid("jpeg: no frame header")


def _ico_size(d: bytes) -> tuple[int, int]:
    if len(d) < 6:
        raise _invalid("ico: truncated")
    (count,) = struct.unpack("<H", d[4:6])
    if count == 0 or len(d) < 6 + 16 * count:
        raise _invalid("ico: bad directory")
    sizes = [(d[6 + 16 * n] or 256, d[7 + 16 * n] or 256) for n in range(count)]
    return max(sizes, key=lambda s: s[0] * s[1])


_SIZE_READERS = {PNG: _png_size, GIF: _gif_size, WEBP: _webp_size, JPEG: _jpeg_size, ICO: _ico_size}


def image_size(mime: str, data: bytes) -> tuple[int, int]:
    """Width and height from a raster image's header (IconImageError when unreadable)."""
    return _SIZE_READERS[mime](data)


# ---- SVG ------------------------------------------------------------------------------


def _local(name: str) -> tuple[str, str]:
    """expat ``"uri local"`` (namespace_separator=" ") -> (uri, local)."""
    uri, _, local = name.rpartition(" ")
    return uri, local


def _safe_ref(value: str) -> bool:
    v = value.strip()
    return v.startswith("#") or bool(_DATA_IMAGE.match(v))


def _check_css(text: str) -> None:
    if "@import" in text.lower():
        raise _invalid("svg: @import")
    for match in _CSS_URL.finditer(text):
        if not _safe_ref(match.group(2)):
            raise _invalid("svg: external url()")


def check_svg(data: bytes) -> None:
    """Raise IconImageError unless ``data`` is an SVG following the module's rules."""
    parser = xml.parsers.expat.ParserCreate(namespace_separator=" ")
    parser.SetParamEntityParsing(xml.parsers.expat.XML_PARAM_ENTITY_PARSING_NEVER)
    depth = 0
    style_depth: int | None = None  # inside <style>: its text is CSS

    def refuse(reason: str) -> Callable[..., Any]:
        def handler(*_args: object) -> Any:
            raise _invalid(reason)

        return handler

    def start(name: str, attrs: dict[str, str]) -> None:
        nonlocal depth, style_depth
        uri, local = _local(name)
        lower = local.lower()
        if depth == 0 and (uri != _SVG_NS or local != "svg"):
            raise _invalid("svg: root is not <svg> in the SVG namespace")
        if lower in _FORBIDDEN_ELEMENTS or uri == _XHTML_NS:
            raise _invalid(f"svg: <{local}>")
        for attr, value in attrs.items():
            _, attr_local = _local(attr)
            a = attr_local.lower()
            if a.startswith("on"):
                raise _invalid(f"svg: {attr_local} attribute")
            if a == "href" and not _safe_ref(value):
                raise _invalid("svg: external href")
            if a == "attributename" and lower in _ANIMATIONS and value.strip().lower().endswith("href"):
                raise _invalid("svg: animated href")
            if a == "style":
                _check_css(value)
        if lower == "style" and style_depth is None:
            style_depth = depth
        depth += 1

    def end(_name: str) -> None:
        nonlocal depth, style_depth
        depth -= 1
        if style_depth == depth:
            style_depth = None

    css: list[str] = []

    def text(chars: str) -> None:
        if style_depth is not None:
            css.append(chars)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    parser.StartDoctypeDeclHandler = refuse("svg: DOCTYPE")
    parser.EntityDeclHandler = refuse("svg: entity declaration")
    parser.ExternalEntityRefHandler = refuse("svg: external entity")
    parser.ProcessingInstructionHandler = refuse("svg: processing instruction")
    try:
        parser.Parse(data, True)
    except xml.parsers.expat.ExpatError:
        raise _invalid("svg: not well-formed XML") from None
    _check_css("".join(css))


# ---- the whole check ------------------------------------------------------------------


def media_type(content_type: str | None) -> str:
    """``"Image/PNG; charset=x"`` -> ``"image/png"``."""
    return (content_type or "").split(";", 1)[0].strip().lower()


def check_image(content_type: str | None, data: bytes) -> str:
    """The canonical type to store for an upload, or IconImageError (see the module docstring)."""
    if len(data) > MAX_BYTES:
        raise IconImageError("too large", 413, "body_too_large")
    claimed = ACCEPTED_TYPES.get(media_type(content_type))
    if claimed is None:
        raise _invalid("unsupported Content-Type")
    if not data:
        raise _invalid("empty")
    found = sniff(data)
    if found != claimed:
        raise _invalid(f"bytes are {found or 'unknown'}, not {claimed}")
    if claimed == SVG:
        check_svg(data)
    else:
        w, h = image_size(claimed, data)
        if not (MIN_PX <= w <= MAX_PX and MIN_PX <= h <= MAX_PX):
            raise _invalid(f"{w}x{h} px is outside {MIN_PX}..{MAX_PX}")
    return claimed


# ---- storage --------------------------------------------------------------------------


@dataclass(frozen=True)
class IconImage:
    mime: str
    sha256: str
    data: bytes
    updated_at: datetime

    @property
    def version(self) -> str:
        return self.sha256[:VERSION_HEX]


def icon_image_url(mcp_id: int, sha256: str) -> str:
    """The relative URL every MCP payload carries (``icon_image``); ``v`` changes with the bytes."""
    return f"/api/mcps/{mcp_id}/icon-image?v={sha256[:VERSION_HEX]}"


class IconImageStore:
    """``mcp_icons`` rows. Event-loop thread only (the shared Database connection)."""

    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def get(self, mcp_id: int) -> IconImage | None:
        rows = self._db.query(
            "SELECT mime, sha256, data, updated_at FROM mcp_icons WHERE mcp_id = ?", (mcp_id,)
        )
        if not rows:
            return None
        r = rows[0]
        return IconImage(r["mime"], r["sha256"], bytes(r["data"]), datetime.fromisoformat(r["updated_at"]))

    def sha256(self, mcp_id: int) -> str | None:
        rows = self._db.query("SELECT sha256 FROM mcp_icons WHERE mcp_id = ?", (mcp_id,))
        return rows[0]["sha256"] if rows else None

    def url(self, mcp_id: int) -> str | None:
        sha = self.sha256(mcp_id)
        return icon_image_url(mcp_id, sha) if sha is not None else None

    def set(self, mcp_id: int, mime: str, data: bytes) -> str:
        """Store (replace) the MCP's image and return its sha256. sqlite3.IntegrityError when the
        MCP does not exist (foreign key)."""
        sha = hashlib.sha256(data).hexdigest()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO mcp_icons (mcp_id, mime, sha256, data, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (mcp_id) DO UPDATE SET mime = excluded.mime, sha256 = excluded.sha256, "
                "data = excluded.data, updated_at = excluded.updated_at",
                (mcp_id, mime, sha, sqlite3.Binary(data), self._clock.now().isoformat()),
            )
        return sha

    def remove(self, mcp_id: int) -> IconImage | None:
        """Delete the MCP's image; the removed one, or None when there was none."""
        old = self.get(mcp_id)
        if old is not None:
            self._db.execute("DELETE FROM mcp_icons WHERE mcp_id = ?", (mcp_id,))
        return old
