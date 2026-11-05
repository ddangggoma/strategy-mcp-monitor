import gzip
import subprocess
import sys

import httpx
import pytest

from app.web.app_factory import create_app
from app.web.static import CSP, IMMUTABLE, pick_variant, safe_parts

JS = b"console.log(1)"


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / ".vite").mkdir()
    (d / ".vite" / "manifest.json").write_text("{}", "utf-8")
    for page in ("board", "admin", "notice"):
        (d / f"{page}.html").write_text(f"<!doctype html><title>{page}</title>", "utf-8")
    (d / "assets" / "board-AbC123.js").write_bytes(JS)
    (d / "assets" / "board-AbC123.js.br").write_bytes(b"BR-BYTES")
    (d / "assets" / "board-AbC123.js.gz").write_bytes(gzip.compress(JS))
    (d / "assets" / "plain-1.css").write_text("a{}", "utf-8")
    (d / "assets" / "blob-1.xyz").write_bytes(b"\x00\x01")
    (d / "favicon.svg").write_text("<svg/>", "utf-8")
    (tmp_path / "secret.txt").write_text("TOP-SECRET", "utf-8")  # outside dist
    return d


def client(services, channel, dist):
    base = "http://127.0.0.1:8700" if channel == "local" else "http://test"
    transport = httpx.ASGITransport(app=create_app(channel, services, dist))
    return httpx.AsyncClient(transport=transport, base_url=base)


@pytest.mark.parametrize("channel", ["local", "external"])
async def test_root_serves_board_with_security_headers(services, dist, channel):
    async with client(services, channel, dist) as c:
        r = await c.get("/")
    assert r.status_code == 200 and "<title>board</title>" in r.text
    assert r.headers["content-type"] == "text/html; charset=utf-8"
    assert r.headers["cache-control"] == "no-cache" and r.headers["content-security-policy"] == CSP
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize("channel", ["local", "external"])
@pytest.mark.parametrize(
    "path", ["/admin", "/admin/", "/admin/mcps/3", "/admin/mcps/3?tab=scripts", "/admin/login"]
)
async def test_admin_spa_fallback(services, dist, channel, path):
    async with client(services, channel, dist) as c:
        r = await c.get(path)
    assert r.status_code == 200 and "<title>admin</title>" in r.text
    assert r.headers["content-security-policy"] == CSP


async def test_notice_page_is_local_only(services, dist):
    async with client(services, "local", dist) as c:
        local = await c.get("/notice")
    async with client(services, "external", dist) as c:
        external = await c.get("/notice")
    assert local.status_code == 200 and "<title>notice</title>" in local.text
    assert (external.status_code, external.json()) == (404, {"error": "not_found"})


async def test_html_is_precompressed_when_a_variant_exists(services, dist):
    (dist / "board.html.gz").write_bytes(gzip.compress(b"<!doctype html><title>gz</title>"))
    async with client(services, "external", dist) as c:
        r = await c.get("/", headers={"Accept-Encoding": "gzip"})
    assert r.headers["content-encoding"] == "gzip" and "<title>gz</title>" in r.text
    assert r.headers["content-type"] == "text/html; charset=utf-8" and r.headers["cache-control"] == "no-cache"


async def test_favicon(services, dist):
    async with client(services, "external", dist) as c:
        r = await c.get("/favicon.svg")
    assert r.status_code == 200 and r.text == "<svg/>"
    assert r.headers["content-type"] == "image/svg+xml" and r.headers["cache-control"] == "no-cache"
    assert r.headers["content-security-policy"] == CSP  # an SVG opened directly may carry scripts


@pytest.mark.parametrize(
    "accept,encoding",
    [("br, gzip", "br"), ("gzip", "gzip"), ("identity", None), ("br;q=0, gzip", "gzip"), (None, None)],
)
async def test_assets_precompressed_and_immutable(services, dist, accept, encoding):
    headers = {"Accept-Encoding": accept} if accept is not None else {"Accept-Encoding": "identity"}
    async with client(services, "external", dist) as c:
        async with c.stream("GET", "/assets/board-AbC123.js", headers=headers) as r:
            raw = b"".join([chunk async for chunk in r.aiter_raw()])  # undecoded bytes as sent
    assert r.status_code == 200 and r.headers["cache-control"] == IMMUTABLE
    assert r.headers["content-type"] == "text/javascript; charset=utf-8" and r.headers["vary"] == "Accept-Encoding"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers.get("content-encoding") == encoding
    decoded = gzip.decompress(raw) if encoding == "gzip" else raw
    assert decoded == (b"BR-BYTES" if encoding == "br" else JS)


async def test_asset_without_variant_falls_back_to_original(services, dist):
    async with client(services, "external", dist) as c:
        r = await c.get("/assets/plain-1.css", headers={"Accept-Encoding": "br, gzip"})
    assert r.status_code == 200 and r.text == "a{}" and "content-encoding" not in r.headers
    assert r.headers["content-type"] == "text/css; charset=utf-8"


async def test_unknown_extension_is_octet_stream(services, dist):
    async with client(services, "external", dist) as c:
        r = await c.get("/assets/blob-1.xyz")
    assert r.status_code == 200 and r.content == b"\x00\x01"
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "path",
    [
        "/assets/missing.js",
        "/assets/",
        "/assets/..%2fboard.html",
        "/assets/..%2f..%2fsecret.txt",
        "/assets/%2e%2e/board.html",
        "/assets/%2e%2e%2fsecret.txt",
        "/assets/..\\board.html",
        "/assets/..%5cboard.html",
        "/assets/%5c%5cserver%5cshare%5cx.js",
        "/assets/C:/Windows/win.ini",
        "/assets/C:%5cWindows%5cwin.ini",
        "/assets//board-AbC123.js",
        "/assets/board-AbC123.js:stream",
        "/assets/board-AbC123.js::$DATA",
        "/assets/board-AbC123.js.br:stream",
        "/assets/CON",
        "/assets/nul",
        "/assets/NUL.js",
        "/assets/COM1",
        "/assets/com9.txt",
        "/assets/LPT1",
        "/assets/CON.",
        "/assets/board-AbC123.js.",
        "/assets/board-AbC123.js%20",
        "/assets/%00board-AbC123.js",
        "/assets/board-AbC123.js%00.png",
        "/assets/.%2e/board.html",
        "/assets/../.vite/manifest.json",
        "/assets/.hidden",
        "/.vite/manifest.json",
        "/board.html",
        "/secret.txt",
    ],
)
async def test_asset_misses_and_traversal_404(services, dist, path):
    async with client(services, "external", dist) as c:
        r = await c.get(path)
    assert (r.status_code, r.json()) == (404, {"error": "not_found"})
    assert "TOP-SECRET" not in r.text


@pytest.mark.parametrize(
    "raw",
    ["..", "../board.html", "a/../b.js", "/etc/passwd", "a//b.js", "a\\b.js", "C:/x", "x.js:s", "x.js::$DATA",
     "CON", "nul.txt", "Com1", "LPT9.js", "aux.", "x.js ", ".env", "a/.hidden", "a\x00b", "a?b", "a*b", "", "a/"],
)
def test_safe_parts_rejects(raw):
    assert safe_parts(raw) is None


def test_safe_parts_accepts_plain_names():
    assert safe_parts("board-AbC123.js") == ("board-AbC123.js",)
    assert safe_parts("fonts/pretendard-1.woff2") == ("fonts", "pretendard-1.woff2")
    assert safe_parts("console.js") == ("console.js",)  # not a device name


async def test_directory_link_pointing_outside_dist_is_404(services, dist, tmp_path):
    link = dist / "assets" / "out"
    if sys.platform == "win32":  # a junction needs no privilege, unlike a symlink
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(tmp_path)], capture_output=True)
        assert made.returncode == 0, made.stderr
    else:
        link.symlink_to(tmp_path, target_is_directory=True)
    assert (link / "secret.txt").read_text("utf-8") == "TOP-SECRET"  # the link really leads out
    async with client(services, "external", dist) as c:
        r = await c.get("/assets/out/secret.txt")
    assert (r.status_code, r.json()) == (404, {"error": "not_found"})


async def test_symlink_pointing_outside_dist_is_404(services, dist, tmp_path):
    link = dist / "assets" / "leak.txt"
    try:
        link.symlink_to(tmp_path / "secret.txt")
    except OSError:
        pytest.skip("symlinks need privileges on this machine")
    async with client(services, "external", dist) as c:
        r = await c.get("/assets/leak.txt")
    assert (r.status_code, r.json()) == (404, {"error": "not_found"})


async def test_variant_symlink_pointing_outside_dist_is_not_served(services, dist, tmp_path):
    link = dist / "assets" / "plain-1.css.gz"
    try:
        link.symlink_to(tmp_path / "secret.txt")
    except OSError:
        pytest.skip("symlinks need privileges on this machine")
    async with client(services, "external", dist) as c:
        r = await c.get("/assets/plain-1.css", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.text == "a{}" and "content-encoding" not in r.headers


async def test_api_paths_stay_json(services, dist):
    async with client(services, "external", dist) as c:
        r = await c.get("/api/nope")
    assert (r.status_code, r.json()) == (404, {"error": "not_found"})


async def test_api_still_wins_over_static(services, dist):
    async with client(services, "local", dist) as c:
        r = await c.get("/api/channel")
    assert r.status_code == 200 and r.json()["channel"] == "local"


async def test_no_static_without_dist(services):
    async with client(services, "external", None) as c:
        assert (await c.get("/")).status_code == 404


async def test_no_static_when_board_html_missing(services, tmp_path):
    empty = tmp_path / "empty-dist"
    empty.mkdir()
    async with client(services, "external", empty) as c:
        assert (await c.get("/")).status_code == 404


def test_pick_variant_prefers_br_then_gzip_then_original(dist):
    js = dist / "assets" / "board-AbC123.js"
    assert pick_variant(js, "br, gzip") == (dist / "assets" / "board-AbC123.js.br", "br")
    assert pick_variant(js, "gzip, deflate") == (dist / "assets" / "board-AbC123.js.gz", "gzip")
    assert pick_variant(js, "BR;Q=0.5") == (dist / "assets" / "board-AbC123.js.br", "br")
    assert pick_variant(js, "*") == (dist / "assets" / "board-AbC123.js.br", "br")
    assert pick_variant(js, "br;q=0, *;q=0.1") == (dist / "assets" / "board-AbC123.js.gz", "gzip")
    assert pick_variant(js, "br;q=0, gzip;q=0") == (js, None)
    assert pick_variant(js, "br;q=abc") == (js, None)
    assert pick_variant(js, "identity") == (js, None)
    assert pick_variant(js, "") == (js, None)
    assert pick_variant(js, None) == (js, None)


def test_pick_variant_falls_back_when_the_variant_is_missing(dist):
    css = dist / "assets" / "plain-1.css"
    assert pick_variant(css, "br, gzip") == (css, None)
    js = dist / "assets" / "board-AbC123.js"
    (dist / "assets" / "board-AbC123.js.br").unlink()
    assert pick_variant(js, "br, gzip") == (dist / "assets" / "board-AbC123.js.gz", "gzip")
