"""The per-MCP icon image (app/monitor/icon_images.py, PUT/DELETE/GET /api/mcps/{id}/icon-image)."""
import hashlib
import sqlite3
import struct
import zlib

import pytest

from app.db import MIGRATIONS, Database
from app.monitor import icon_images
from app.monitor.icon_images import MAX_BYTES, IconImageError, check_image, check_svg
from tests.mcp_helpers import login_as, make_user, seed_mcp
from tests.test_auth_api import audit_events

# ---- image builders ---------------------------------------------------------------------


def png(w: int = 32, h: int = 32) -> bytes:
    """A real (decodable) RGBA PNG, all transparent."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    raw = b"".join(b"\x00" + b"\x00" * (4 * w) for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def gif(w: int = 32, h: int = 32) -> bytes:
    return b"GIF89a" + struct.pack("<HH", w, h) + b"\x00\x00\x00" + b"\x2c" + b"\x00" * 9 + b"\x02\x02\x44\x01\x00\x3b"


def jpeg(w: int = 32, h: int = 32) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, h, w, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def webp(kind: str = "VP8L", w: int = 32, h: int = 32) -> bytes:
    if kind == "VP8L":
        body = b"\x2f" + ((w - 1) | ((h - 1) << 14)).to_bytes(4, "little") + b"\x00" * 4
    elif kind == "VP8 ":
        body = b"\x00\x00\x00" + b"\x9d\x01\x2a" + struct.pack("<HH", w, h) + b"\x00" * 4
    else:  # VP8X
        body = b"\x00" * 4 + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    chunk = kind.encode() + struct.pack("<I", len(body)) + body
    return b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk


def ico(*sizes: int) -> bytes:
    sizes = sizes or (32,)
    head = b"\x00\x00\x01\x00" + struct.pack("<H", len(sizes))
    entries = b"".join(bytes([s % 256, s % 256]) + b"\x00\x00\x01\x00\x20\x00" + struct.pack("<II", 40, 0) for s in sizes)
    return head + entries + b"\x00" * 40


SVG_OK = (b'<?xml version="1.0" encoding="UTF-8"?>\n'
          b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 24 24">'
          b'<defs><linearGradient id="g"><stop offset="0" stop-color="#f60"/></linearGradient></defs>'
          b'<style>.a{fill:url(#g)}</style><!-- a comment -->'
          b'<circle class="a" cx="12" cy="12" r="10" style="stroke:url(\'#g\')"/>'
          b'<use xlink:href="#g"/><image href="data:image/png;base64,iVBORw0KGgo=" width="4" height="4"/></svg>')


def svg(inner: str, attrs: str = "") -> bytes:
    return f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"{attrs}>{inner}</svg>'.encode()


FORMATS = [
    ("image/png", png(), "image/png"),
    ("image/jpeg", jpeg(), "image/jpeg"),
    ("image/webp", webp("VP8L"), "image/webp"),
    ("image/webp", webp("VP8 "), "image/webp"),
    ("image/webp", webp("VP8X"), "image/webp"),
    ("image/gif", gif(), "image/gif"),
    ("image/x-icon", ico(16, 48), "image/x-icon"),
    ("image/vnd.microsoft.icon", ico(), "image/x-icon"),
    ("image/svg+xml", SVG_OK, "image/svg+xml"),
    ("image/svg+xml; charset=utf-8", b"\xef\xbb\xbf  " + svg('<rect width="1" height="1"/>'), "image/svg+xml"),
    ("Image/PNG", png(16, 1024), "image/png"),
]


# ---- the checks (no HTTP) ---------------------------------------------------------------


@pytest.mark.parametrize(("ctype", "data", "canonical"), FORMATS, ids=lambda v: v if isinstance(v, str) else "")
def test_each_format_is_accepted_and_canonicalized(ctype, data, canonical):
    assert check_image(ctype, data) == canonical


@pytest.mark.parametrize(("ctype", "data"), [
    ("image/jpeg", png()),            # bytes are a PNG
    ("image/png", jpeg()),
    ("image/gif", webp()),
    ("image/webp", gif()),
    ("image/x-icon", png()),
    ("image/png", SVG_OK),            # text claimed as a raster
    ("image/svg+xml", png()),         # a raster claimed as SVG
    ("image/png", b"hello world"),
    ("image/png", b""),
    ("text/plain", png()),            # not an accepted type at all
    ("application/octet-stream", png()),
    ("image/bmp", b"BM" + b"\x00" * 60),
    (None, png()),
    ("image/png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDX" + b"\x00" * 20),  # no IHDR
    ("image/jpeg", b"\xff\xd8\xff\xd9"),                                       # no frame header
    ("image/webp", b"RIFF\x10\x00\x00\x00WEBPABCD" + b"\x00" * 20),            # unknown chunk
    ("image/x-icon", b"\x00\x00\x01\x00\x00\x00"),                             # no entries
])
def test_bytes_must_match_the_claimed_type(ctype, data):
    with pytest.raises(IconImageError) as e:
        check_image(ctype, data)
    assert (e.value.status, e.value.code) == (422, "validation")


@pytest.mark.parametrize("data", [png(15, 32), png(32, 15), png(1025, 32), png(32, 1025), gif(8, 8),
                                  jpeg(2000, 100), webp("VP8X", 4096, 64), ico(8)])
def test_raster_size_outside_16_to_1024_px_is_refused(data):
    with pytest.raises(IconImageError):
        check_image(icon_images.sniff(data), data)


def test_size_limit_is_256_kib():
    at_limit = png() + b"\x00" * (MAX_BYTES - len(png()))
    assert len(at_limit) == MAX_BYTES and check_image("image/png", at_limit) == "image/png"
    with pytest.raises(IconImageError) as e:
        check_image("image/png", at_limit + b"\x00")
    assert (e.value.status, e.value.code) == (413, "body_too_large")


BILLION_LAUGHS = (b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;">]>'
                  b'<svg xmlns="http://www.w3.org/2000/svg"><text>&b;</text></svg>')


@pytest.mark.parametrize("data", [
    BILLION_LAUGHS,
    b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">' + svg(""),
    b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///c:/windows/win.ini">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
    svg("<script>alert(1)</script>"),
    svg('<script xlink:href="#x"/>'),
    svg("<SCRIPT>alert(1)</SCRIPT>"),
    svg('<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">x</div></foreignObject>'),
    svg('<g><iframe src="https://x"/></g>'),
    svg('<html:img xmlns:html="http://www.w3.org/1999/xhtml" src="x"/>'),
    svg("", ' onload="alert(1)"'),
    svg('<rect ONCLICK="alert(1)"/>'),
    svg('<image href="https://evil.example/a.png"/>'),
    svg('<image xlink:href="http://evil.example/a.png"/>'),
    svg('<a href="javascript:alert(1)"><rect/></a>'),
    svg('<image href="data:image/svg+xml;base64,PHN2Zy8+"/>'),
    svg('<image href="//evil.example/a.png"/>'),
    svg('<use href="other.svg#x"/>'),
    svg('<a><set attributeName="href" to="javascript:alert(1)"/></a>'),
    svg('<a><animate attributeName="xlink:href" values="javascript:alert(1)"/></a>'),
    svg("<style>@import url(https://evil.example/a.css);</style>"),
    svg("<style>rect{fill:url(https://evil.example/p.svg#a)}</style>"),
    svg("<style><![CDATA[ rect{background:url( 'http://x/y.png' )} ]]></style>"),
    svg('<rect style="fill:url(https://evil.example/x)"/>'),
    b'<?xml-stylesheet href="https://evil.example/a.css"?>' + svg(""),
    b"<html><body>hi</body></html>",
    b'<svg viewBox="0 0 1 1"/>',                         # no SVG namespace: not drawn by <img>
    b'<svg xmlns="http://www.w3.org/2000/svg"><rect>',   # not well-formed
    b'<svg xmlns="http://www.w3.org/2000/svg"><use xlink:href="#a"/></svg>',  # unbound prefix
    b"<!-- only a comment -->",
])
def test_unsafe_or_broken_svg_is_refused(data):
    with pytest.raises(IconImageError) as e:
        check_image("image/svg+xml", data)
    assert e.value.code == "validation"


def test_safe_svg_references_pass():
    check_svg(SVG_OK)
    check_svg(svg('<a href=" #top"><rect/></a><animate attributeName="opacity" to="0"/>'))
    check_svg(svg('<image href="data:image/webp;base64,UklGRg=="/><image href="DATA:image/gif,x"/>'))


# ---- HTTP -------------------------------------------------------------------------------


def url_of(mcp_id: int, data: bytes) -> str:
    return f"/api/mcps/{mcp_id}/icon-image?v={hashlib.sha256(data).hexdigest()[:12]}"


async def put_image(client, mcp_id, data, ctype="image/png", headers=None):
    return await client.put(f"/api/mcps/{mcp_id}/icon-image", content=data,
                            headers={"Content-Type": ctype, **(headers or {})})


@pytest.mark.parametrize(("ctype", "data", "canonical"), FORMATS[:9], ids=lambda v: v if isinstance(v, str) else "")
async def test_upload_then_serve_each_format(external_client, services, ctype, data, canonical):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    h = {"X-CSRF-Token": login_as(external_client, services, owner, "external")}
    r = await put_image(external_client, m.id, data, ctype, h)
    assert r.status_code == 200, r.text
    assert r.json()["icon_image"] == url_of(m.id, data) and r.json()["live"]["icon_image"] == url_of(m.id, data)
    external_client.cookies.clear()  # the board is anonymous: so is its image
    g = await external_client.get(url_of(m.id, data))
    assert g.status_code == 200 and g.content == data
    assert g.headers["content-type"] == canonical


async def test_get_headers_cache_and_etag(external_client, local_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    h = {"X-CSRF-Token": login_as(local_client, services, owner, "local")}
    data = SVG_OK
    assert (await put_image(local_client, m.id, data, "image/svg+xml", h)).status_code == 200
    sha = hashlib.sha256(data).hexdigest()
    for client in (external_client, local_client):  # both channels
        g = await client.get(url_of(m.id, data))
        assert g.status_code == 200
        assert g.headers["content-type"] == "image/svg+xml"
        assert g.headers["x-content-type-options"] == "nosniff"
        assert g.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        assert g.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert g.headers["etag"] == f'"{sha}"'
    for stale in (f"/api/mcps/{m.id}/icon-image", f"/api/mcps/{m.id}/icon-image?v=000000000000"):
        g = await external_client.get(stale)
        assert g.status_code == 200 and g.headers["cache-control"] == "no-cache"
    g = await external_client.get(f"/api/mcps/{m.id}/icon-image", headers={"If-None-Match": f'"{sha}"'})
    assert g.status_code == 304 and g.content == b"" and g.headers["etag"] == f'"{sha}"'
    g = await external_client.get(f"/api/mcps/{m.id}/icon-image", headers={"If-None-Match": '"other"'})
    assert g.status_code == 200


async def test_get_without_an_image_is_404(external_client, services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    for path in (f"/api/mcps/{m.id}/icon-image", "/api/mcps/999/icon-image"):
        r = await external_client.get(path)
        assert (r.status_code, r.json()) == (404, {"error": "not_found"})


async def test_payloads_carry_the_url_and_the_board_is_republished(external_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner, icon="🧮")
    h = {"X-CSRF-Token": login_as(external_client, services, owner, "external")}
    assert (await external_client.get("/api/board")).json()["mcps"][0]["icon_image"] is None
    assert (await external_client.get(f"/api/mcps/{m.id}")).json()["icon_image"] is None
    before = services.bus.version(m.id)
    sub = services.bus.subscribe()
    data = png(64, 64)
    r = await put_image(external_client, m.id, data, headers=h)
    assert r.json()["icon"] == "🧮"  # the emoji stays: it is the fallback
    assert services.bus.version(m.id) == before + 1 and m.id in sub.dirty  # SSE sends the item again
    assert services.monitor.batch_item(m.id)["icon_image"] == url_of(m.id, data)
    assert (await external_client.get("/api/board")).json()["mcps"][0]["icon_image"] == url_of(m.id, data)
    assert (await external_client.get("/api/mcps")).json()[0]["icon_image"] == url_of(m.id, data)
    # a new image, a new URL
    data2 = png(48, 48)
    r = await put_image(external_client, m.id, data2, headers=h)
    assert r.json()["icon_image"] == url_of(m.id, data2) != url_of(m.id, data)
    sub.dirty.clear()
    r = await external_client.delete(f"/api/mcps/{m.id}/icon-image", headers=h)
    assert r.status_code == 200 and r.json()["icon_image"] is None and r.json()["live"]["icon_image"] is None
    assert m.id in sub.dirty
    assert (await external_client.get("/api/board")).json()["mcps"][0]["icon_image"] is None
    services.bus.unsubscribe(sub)


async def test_delete_is_idempotent(external_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    h = {"X-CSRF-Token": login_as(external_client, services, owner, "external")}
    for _ in range(2):
        r = await external_client.delete(f"/api/mcps/{m.id}/icon-image", headers=h)
        assert r.status_code == 200 and r.json()["icon_image"] is None
    r = await external_client.delete("/api/mcps/999/icon-image", headers=h)
    assert (r.status_code, r.json()) == (404, {"error": "not_found"})


async def test_http_refusals(external_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    h = {"X-CSRF-Token": login_as(external_client, services, owner, "external")}
    r = await put_image(external_client, m.id, png(), "image/jpeg", h)
    assert (r.status_code, r.json()) == (422, {"error": "validation"})
    r = await put_image(external_client, m.id, svg("<script/>"), "image/svg+xml", h)
    assert (r.status_code, r.json()) == (422, {"error": "validation"})
    big = png() + b"\x00" * MAX_BYTES
    r = await put_image(external_client, m.id, big, headers=h)  # declared Content-Length
    assert (r.status_code, r.json()) == (413, {"error": "body_too_large"})

    async def chunked():  # no Content-Length: the bytes are counted
        for i in range(0, len(big), 65536):
            yield big[i:i + 65536]
    r = await external_client.put(f"/api/mcps/{m.id}/icon-image", content=chunked(), headers={"Content-Type": "image/png", **h})
    assert (r.status_code, r.json()) == (413, {"error": "body_too_large"})
    r = await put_image(external_client, 999, png(), headers=h)
    assert (r.status_code, r.json()) == (404, {"error": "not_found"})
    assert services.icon_images.get(m.id) is None


async def test_permissions_mirror_the_settings_put(external_client, local_client, services):
    """Same rule as PUT /api/mcps/{id} (EDIT_MCP_SETTINGS): any signed-in user, on both channels."""
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    other = make_user(services, "d@x.com"); admin = make_user(services, "a@x.com", "admin")
    # anonymous: refused (but may read the image)
    r = await put_image(external_client, m.id, png())
    assert (r.status_code, r.json()) == (401, {"error": "login_required"})
    assert (await external_client.delete(f"/api/mcps/{m.id}/icon-image")).status_code == 401
    # a session without the CSRF header: refused
    login_as(external_client, services, owner, "external")
    r = await put_image(external_client, m.id, png())
    assert (r.status_code, r.json()) == (403, {"error": "csrf"})
    # owner (external), developer who does not own it (external), admin (local): allowed
    for client, user, channel in ((external_client, owner, "external"), (external_client, other, "external"),
                                  (local_client, admin, "local")):
        client.cookies.clear()
        h = {"X-CSRF-Token": login_as(client, services, user, channel)}
        data = png(16 + user.id, 16 + user.id)
        assert (await put_image(client, m.id, data, headers=h)).status_code == 200, user.email
        assert services.icon_images.get(m.id).data == data
        assert (await client.put(f"/api/mcps/{m.id}", json={"icon": "🤖"}, headers=h)).status_code == 200  # same rule
    ev = [e for e in await audit_events(services, "admin.audit") if e["result"] == "denied"]
    assert {e["action"] for e in ev} == {"edit_mcp_settings"} and any(e["target"].get("reason") == "csrf" for e in ev)


async def test_audit_rows(external_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    h = {"X-CSRF-Token": login_as(external_client, services, owner, "external")}
    data = ico(32)
    await put_image(external_client, m.id, data, "image/vnd.microsoft.icon", h)
    await put_image(external_client, m.id, png(), "image/gif", h)
    await put_image(external_client, m.id, png() + b"\x00" * MAX_BYTES, headers=h)
    await put_image(external_client, 999, png(), headers=h)
    await external_client.delete(f"/api/mcps/{m.id}/icon-image", headers=h)
    await external_client.delete(f"/api/mcps/{m.id}/icon-image", headers=h)  # no-op: not audited
    await external_client.delete("/api/mcps/999/icon-image", headers=h)
    ev = [(e["action"], e["result"], e["target"])
          for e in await audit_events(services, "admin.audit") if e["action"].startswith("mcp_icon_image")]
    sha = hashlib.sha256(data).hexdigest()[:12]
    assert ev == [
        ("mcp_icon_image_set", "ok", {"mcp_id": m.id, "mime": "image/x-icon", "bytes": len(data), "sha256": sha}),
        ("mcp_icon_image_set", "error", {"mcp_id": m.id, "bytes": len(png()), "mime": "image/gif", "error": "validation"}),
        ("mcp_icon_image_set", "error", {"mcp_id": m.id, "bytes": len(png()) + MAX_BYTES, "error": "body_too_large"}),
        ("mcp_icon_image_set", "error", {"mcp_id": 999, "error": "not_found"}),
        ("mcp_icon_image_remove", "ok", {"mcp_id": m.id, "mime": "image/x-icon", "bytes": len(data), "sha256": sha}),
        ("mcp_icon_image_remove", "error", {"mcp_id": 999, "error": "not_found"}),
    ]


async def test_deleting_the_mcp_deletes_its_image(local_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    h = {"X-CSRF-Token": login_as(local_client, services, owner, "local")}
    assert (await put_image(local_client, m.id, png(), headers=h)).status_code == 200
    assert services.db.query("SELECT COUNT(*) FROM mcp_icons")[0][0] == 1
    assert (await local_client.delete(f"/api/mcps/{m.id}", headers=h)).status_code == 204
    assert services.db.query("SELECT COUNT(*) FROM mcp_icons")[0][0] == 0
    assert (await local_client.get(f"/api/mcps/{m.id}/icon-image")).status_code == 404


def test_store_refuses_an_unknown_mcp(services):
    with pytest.raises(sqlite3.IntegrityError):
        services.icon_images.set(12345, "image/png", png())


def test_migration_9_from_an_existing_v8_database(paths):
    path = paths.db_path
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    for script in MIGRATIONS[:8]:
        conn.executescript(script)
    conn.execute("PRAGMA user_version = 8")
    conn.execute("INSERT INTO mcps (name, host, port, config, created_at) VALUES ('calc', '127.0.0.1', 9102, '{}', '2026-11-01T00:00:00+00:00')")
    conn.commit(); conn.close()
    db = Database(path)
    try:
        db.migrate()
        assert db.query("PRAGMA user_version")[0][0] == len(MIGRATIONS) == 9
        assert [r["name"] for r in db.query("SELECT name FROM mcps")] == ["calc"]  # existing rows kept
        cols = {r["name"] for r in db.query("PRAGMA table_info(mcp_icons)")}
        assert cols == {"mcp_id", "mime", "sha256", "data", "updated_at"}
        fk = db.query("PRAGMA foreign_key_list(mcp_icons)")[0]
        assert (fk["table"], fk["on_delete"]) == ("mcps", "CASCADE")
        db.execute("INSERT INTO mcp_icons VALUES (1, 'image/png', 'x', x'00', 't')")
        db.execute("DELETE FROM mcps WHERE id = 1")
        assert db.query("SELECT COUNT(*) FROM mcp_icons")[0][0] == 0
    finally:
        db.close()
