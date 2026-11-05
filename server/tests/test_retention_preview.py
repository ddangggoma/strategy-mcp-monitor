from datetime import date

from app.logstore.retention import preview, retention_cutoff
from tests.test_auth_api import bootstrap, login


def test_cutoff_keeps_exactly_days_dates():
    assert retention_cutoff(date(2026, 11, 4), 7) == date(2026, 10, 29)
    assert retention_cutoff(date(2026, 11, 4), 180) == date(2026, 5, 9)


def test_preview_counts_only_log_files(tmp_path):
    for name, size in [("2026-10-27.jsonl", 10), ("2026-10-28.jsonl.gz", 20), ("2026-10-29.jsonl", 30),
                       ("2026-11-04.jsonl", 40), ("notes.txt", 999), ("2026-13-01.jsonl", 999)]:
        (tmp_path / name).write_bytes(b"x" * size)
    p = preview(tmp_path, date(2026, 11, 4), 7)
    assert (p.days, p.cutoff) == (7, date(2026, 10, 29))
    assert (p.total_files, p.total_bytes, p.oldest_date) == (4, 100, date(2026, 10, 27))
    assert (p.delete_files, p.delete_bytes, p.delete_from, p.delete_to) == (2, 30, date(2026, 10, 27), date(2026, 10, 28))


def test_preview_nothing_to_delete(tmp_path):
    (tmp_path / "2026-11-04.jsonl").write_bytes(b"x")
    p = preview(tmp_path, date(2026, 11, 4), 180)
    assert (p.delete_files, p.delete_bytes, p.delete_from, p.delete_to) == (0, 0, None, None)
    assert (p.total_files, p.oldest_date) == (1, date(2026, 11, 4))


def test_preview_empty_or_missing_dir(tmp_path):
    for d in (tmp_path, tmp_path / "missing"):
        p = preview(d, date(2026, 11, 4), 30)
        assert (p.total_files, p.total_bytes, p.oldest_date, p.delete_files) == (0, 0, None, 0)


def test_preview_ignores_lookalikes(tmp_path):
    # a directory with a log name, a wrong extension, an extra suffix or prefix and a short date are not logs
    (tmp_path / "2026-01-01.jsonl").mkdir()
    for name in ("2026-01-01.json", "2026-01-01.jsonl.gz.tmp", "x2026-01-01.jsonl", "2026-1-1.jsonl"):
        (tmp_path / name).write_bytes(b"x" * 7)
    (tmp_path / "2026-01-02.jsonl").write_bytes(b"x" * 3)
    p = preview(tmp_path, date(2026, 11, 4), 7)
    assert (p.total_files, p.total_bytes, p.delete_files, p.delete_from) == (1, 3, 1, date(2026, 1, 2))


async def test_preview_route_local_admin_only(local_client, external_client, services):
    # conftest clock 2026-11-04 05:00 UTC = KST 14:00, the same day
    (services.paths.logs_dir / "2026-10-01.jsonl").write_bytes(b"x" * 5)
    await bootstrap(local_client); await login(local_client, services)
    r = await local_client.get("/api/settings/retention/preview", params={"days": 7})
    assert r.status_code == 200 and r.json()["cutoff"] == "2026-10-29"
    body = r.json()
    assert body["days"] == 7 and body["delete_from"] == "2026-10-01" and body["delete_to"] == "2026-10-01"
    assert body["delete_files"] == 1 and body["delete_bytes"] == 5
    assert body["oldest_date"] == "2026-10-01" and body["total_files"] >= 1
    assert (await local_client.get("/api/settings/retention/preview", params={"days": 6})).status_code == 422
    assert (await local_client.get("/api/settings/retention/preview", params={"days": 3651})).status_code == 422
    assert (await local_client.get("/api/settings/retention/preview")).status_code == 422
    assert (await external_client.get("/api/settings/retention/preview", params={"days": 7})).status_code == 404


async def test_preview_route_requires_admin(local_client, services):
    from tests.mcp_helpers import login_as, make_user
    assert (await local_client.get("/api/settings/retention/preview", params={"days": 7})).status_code == 401
    login_as(local_client, services, make_user(services, "d@x.com"), "local")
    assert (await local_client.get("/api/settings/retention/preview", params={"days": 7})).status_code == 403
