from app.notice.defaults import DEFAULT_NOTICE
from tests.mcp_helpers import login_as, make_user
from tests.test_auth_api import audit_events, bootstrap, login

BODY = {"title": "안내", "body": "**중요**\n- 기록", "button_text": "확인"}


async def _admin(local_client, services):
    await bootstrap(local_client); await login(local_client, services)
    return {"X-CSRF-Token": local_client.csrf}


async def _notice_events(services):
    return [e for e in await audit_events(services, "admin.audit") if e["action"].startswith("notice_")]


async def test_notice_flow(local_client, services):
    await bootstrap(local_client); await login(local_client, services); h = {"X-CSRF-Token": local_client.csrf}
    assert (await local_client.get("/api/notice")).json()["version"] == 0
    r = await local_client.put("/api/notice", json=BODY, headers=h)
    assert r.status_code == 200 and r.json()["version"] == 1 and r.json()["author"]["email"] == "admin@x.com"
    assert (await local_client.put("/api/notice", json=BODY, headers=h)).json()["version"] == 1   # no-op
    await local_client.put("/api/notice", json={**BODY, "title": "새 안내"}, headers=h)
    vs = (await local_client.get("/api/notice/versions")).json()
    assert [v["version"] for v in vs] == [2, 1] and set(vs[0]) == {"version", "title", "created_at", "author", "reverted_from"}
    r = await local_client.post("/api/notice/versions/1/revert", headers=h)
    assert (r.json()["version"], r.json()["title"], r.json()["reverted_from"]) == (3, "안내", 1)
    assert (await local_client.get("/api/notice/versions/0")).json()["created_at"] is None
    assert (await local_client.post("/api/notice/versions/42/revert", headers=h)).status_code == 404
    events = [e for e in await audit_events(services, "admin.audit") if e["action"].startswith("notice_")]
    assert [e["action"] for e in events][:3] == ["notice_update", "notice_update", "notice_revert"]


async def test_notice_validation_422(local_client, services):
    await bootstrap(local_client); await login(local_client, services)
    r = await local_client.put("/api/notice", json={**BODY, "title": ""}, headers={"X-CSRF-Token": local_client.csrf})
    assert (r.status_code, r.json()) == (422, {"error": "validation"})


async def test_notice_admin_only(local_client, services):
    await bootstrap(local_client)
    login_as(local_client, services, make_user(services, "d@x.com"), "local")
    assert (await local_client.get("/api/notice")).status_code == 403


async def test_notice_routes_404_on_external(external_client):
    for method, path in [("GET", "/api/notice"), ("PUT", "/api/notice"), ("GET", "/api/notice/versions"), ("POST", "/api/notice/versions/1/revert")]:
        assert (await external_client.request(method, path, json={})).status_code == 404


# ---- beyond the plan's tests -------------------------------------------------------


async def test_get_notice_json_shape(local_client, services):
    h = await _admin(local_client, services)
    default = (await local_client.get("/api/notice")).json()
    assert default == {
        "version": 0, "title": DEFAULT_NOTICE.title, "body": DEFAULT_NOTICE.body,
        "button_text": DEFAULT_NOTICE.button_text, "created_at": None, "author": None,
        "reverted_from": None,
    }
    saved = (await local_client.put("/api/notice", json=BODY, headers=h)).json()
    assert saved["created_at"] == "2026-11-04T14:00:00.000+09:00"  # KST, millisecond precision
    assert set(saved) == set(default)
    assert saved["author"] == {"id": 1, "email": "admin@x.com", "name": "관리자"}
    assert (saved["title"], saved["body"], saved["button_text"]) == ("안내", "**중요**\n- 기록", "확인")
    assert (await local_client.get("/api/notice")).json() == saved


async def test_put_normalizes_what_it_stores(local_client, services):
    h = await _admin(local_client, services)
    r = await local_client.put(
        "/api/notice", json={"title": " 안내 ", "body": "\r\n줄1  \r\n줄2\r\n", "button_text": " 확인"}, headers=h
    )
    assert (r.json()["title"], r.json()["body"], r.json()["button_text"]) == ("안내", "줄1\n줄2", "확인")
    # the same text, written differently, is the same content: no new version
    again = await local_client.put(
        "/api/notice", json={"title": "안내", "body": "줄1\n줄2", "button_text": "확인"}, headers=h
    )
    assert again.json()["version"] == 1


async def test_get_versions_list_and_single(local_client, services):
    h = await _admin(local_client, services)
    assert (await local_client.get("/api/notice/versions")).json() == []  # version 0 is not listed
    await local_client.put("/api/notice", json=BODY, headers=h)
    services.clock.advance(60)
    await local_client.put("/api/notice", json={**BODY, "title": "둘"}, headers=h)
    vs = (await local_client.get("/api/notice/versions")).json()
    assert [v["title"] for v in vs] == ["둘", "안내"]
    assert vs[0]["created_at"] == "2026-11-04T14:01:00.000+09:00"
    assert vs[0]["author"]["email"] == "admin@x.com" and vs[0]["reverted_from"] is None
    one = (await local_client.get("/api/notice/versions/1")).json()
    assert (one["version"], one["title"], one["body"]) == (1, "안내", "**중요**\n- 기록")
    zero = (await local_client.get("/api/notice/versions/0")).json()
    assert (zero["version"], zero["title"], zero["author"]) == (0, DEFAULT_NOTICE.title, None)
    r = await local_client.get("/api/notice/versions/9")
    assert (r.status_code, r.json()) == (404, {"error": "not_found"})


async def test_revert_to_default_version_zero(local_client, services):
    """F20: version 0 (built-in text) is a valid revert target."""
    h = await _admin(local_client, services)
    await local_client.put("/api/notice", json=BODY, headers=h)
    r = await local_client.post("/api/notice/versions/0/revert", headers=h)
    assert r.status_code == 200
    j = r.json()
    assert (j["version"], j["reverted_from"], j["title"], j["body"], j["button_text"]) == (
        2, 0, DEFAULT_NOTICE.title, DEFAULT_NOTICE.body, DEFAULT_NOTICE.button_text,
    )
    assert (await local_client.get("/api/notice")).json() == j
    # already on the default text: nothing new
    again = await local_client.post("/api/notice/versions/0/revert", headers=h)
    assert again.status_code == 200 and again.json()["version"] == 2
    events = await _notice_events(services)
    assert [e["action"] for e in events] == ["notice_update", "notice_revert"]
    assert events[1]["target"]["from_version"] == 0 and events[1]["target"]["version"] == 2


async def test_revert_to_current_content_is_a_noop(local_client, services):
    h = await _admin(local_client, services)
    await local_client.put("/api/notice", json=BODY, headers=h)
    r = await local_client.post("/api/notice/versions/1/revert", headers=h)
    assert (r.status_code, r.json()["version"]) == (200, 1)
    assert [e["action"] for e in await _notice_events(services)] == ["notice_update"]


async def test_path_version_bounds(local_client, services):
    h = await _admin(local_client, services)
    for bad in ("-1", "abc", str(2**63)):
        assert (await local_client.get(f"/api/notice/versions/{bad}")).status_code == 422, bad
        r = await local_client.post(f"/api/notice/versions/{bad}/revert", headers=h)
        assert (r.status_code, r.json()) == (422, {"error": "validation"}), bad
    big = str(2**63 - 1)
    assert (await local_client.get(f"/api/notice/versions/{big}")).status_code == 404
    assert (await local_client.post(f"/api/notice/versions/{big}/revert", headers=h)).status_code == 404


async def test_validation_failures_are_422_and_audited(local_client, services):
    h = await _admin(local_client, services)
    bad_bodies = [
        {**BODY, "title": "x" * 81},
        {**BODY, "body": "x" * 4001},
        {**BODY, "button_text": ""},
        {**BODY, "title": "a\x07"},
        {**BODY, "extra": 1},
        {"title": "안내"},
        {**BODY, "title": 5},
    ]
    for bad in bad_bodies:
        r = await local_client.put("/api/notice", json=bad, headers=h)
        assert (r.status_code, r.json()) == (422, {"error": "validation"}), bad
    assert (await local_client.get("/api/notice")).json()["version"] == 0
    events = await _notice_events(services)
    assert len(events) == len(bad_bodies)
    assert all(e["action"] == "notice_update" and e["result"] == "error" for e in events)
    assert all(e["target"]["error"] == "validation" for e in events)


async def test_non_object_body_is_422(local_client, services):
    h = await _admin(local_client, services)
    r = await local_client.put("/api/notice", json=["x"], headers=h)
    assert (r.status_code, r.json()) == (422, {"error": "validation"})


async def test_failed_revert_is_audited_as_error(local_client, services):
    h = await _admin(local_client, services)
    assert (await local_client.post("/api/notice/versions/7/revert", headers=h)).status_code == 404
    [event] = await _notice_events(services)
    assert (event["action"], event["result"]) == ("notice_revert", "error")
    assert event["target"] == {"from_version": 7, "error": "not_found"}


async def test_audit_never_contains_notice_text(local_client, services):
    h = await _admin(local_client, services)
    secret_body = "비밀-본문-문장 SECRET-BODY"
    await local_client.put(
        "/api/notice", json={"title": "비밀-제목", "body": secret_body, "button_text": "비밀-버튼"}, headers=h
    )
    await local_client.put(
        "/api/notice", json={"title": "비밀-제목2", "body": "x" * 3000, "button_text": "확인"}, headers=h
    )
    await local_client.post("/api/notice/versions/1/revert", headers=h)
    events = await _notice_events(services)
    assert [e["action"] for e in events] == ["notice_update", "notice_update", "notice_revert"]
    for e in events:
        assert e["result"] == "ok"
        assert set(e["target"]) == {"version", "from_version", "sha256", "body_chars"}
        assert len(e["target"]["sha256"]) == 64
    assert events[0]["target"]["version"] == 1 and events[0]["target"]["from_version"] == 0
    assert events[1]["target"]["from_version"] == 1 and events[1]["target"]["body_chars"] == 3000
    assert events[2]["target"]["from_version"] == 1 and events[2]["target"]["version"] == 3
    # reverting restores the content of version 1, so the digest equals version 1's
    assert events[2]["target"]["sha256"] == events[0]["target"]["sha256"]
    dump = (services.paths.logs_dir / "2026-11-04.jsonl").read_text("utf-8")
    for text in ("비밀-본문", "SECRET-BODY", "비밀-제목", "비밀-버튼", "x" * 50):
        assert text not in dump


async def test_audit_records_actor_channel_and_ip(local_client, services):
    h = await _admin(local_client, services)
    await local_client.put("/api/notice", json=BODY, headers=h)
    [event] = await _notice_events(services)
    assert (event["actor_email"], event["channel"]) == ("admin@x.com", "local")


async def test_anonymous_is_401_and_nothing_changes(local_client, services):
    await bootstrap(local_client)
    for method, path in [("GET", "/api/notice"), ("PUT", "/api/notice"), ("GET", "/api/notice/versions"),
                         ("GET", "/api/notice/versions/0"), ("POST", "/api/notice/versions/0/revert")]:
        r = await local_client.request(method, path, json=BODY if method == "PUT" else None)
        assert (r.status_code, r.json()) == (401, {"error": "login_required"}), (method, path)
    assert services.notice.current().version == 0 and services.notice.versions() == []


async def test_developer_cannot_write_or_list(local_client, services):
    await bootstrap(local_client)
    csrf = login_as(local_client, services, make_user(services, "d@x.com"), "local")
    h = {"X-CSRF-Token": csrf}
    for method, path in [("GET", "/api/notice"), ("GET", "/api/notice/versions"), ("GET", "/api/notice/versions/0"),
                         ("PUT", "/api/notice"), ("POST", "/api/notice/versions/0/revert")]:
        r = await local_client.request(method, path, headers=h, json=BODY if method == "PUT" else None)
        assert (r.status_code, r.json()) == (403, {"error": "forbidden"}), (method, path)
    assert services.notice.versions() == []


async def test_writes_need_the_csrf_token(local_client, services):
    await _admin(local_client, services)
    r = await local_client.put("/api/notice", json=BODY)
    assert (r.status_code, r.json()) == (403, {"error": "csrf"})
    r = await local_client.post("/api/notice/versions/0/revert")
    assert (r.status_code, r.json()) == (403, {"error": "csrf"})
    assert services.notice.versions() == []


async def test_removed_author_still_lists(local_client, services):
    """A version whose author no longer resolves reports author null rather than failing."""
    h = await _admin(local_client, services)
    await local_client.put("/api/notice", json=BODY, headers=h)
    services.db.execute("UPDATE notice_versions SET author_id = 999")
    assert (await local_client.get("/api/notice")).json()["author"] is None
    assert (await local_client.get("/api/notice/versions")).json()[0]["author"] is None
