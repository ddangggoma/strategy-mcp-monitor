import pytest

from app.winsvc.start_type import NullConfigurator, ScmConfigurator, StartTypeManager
from tests.fakes import FakeScm
from tests.mcp_helpers import login_as, make_user
from tests.test_auth_api import audit_events, bootstrap, login
from tests.winfakes import ListLog


@pytest.mark.parametrize("scm,result,applied", [
    (FakeScm(start="auto"), "applied", ["delayed-auto"]),
    (FakeScm(start="delayed-auto"), "in_sync", []),
    (FakeScm(installed=False), "not_installed", []),
    (FakeScm(start="manual", fail=PermissionError(5, "denied")), "denied", []),
    # OSError(1, ...) would construct a PermissionError (EPERM): use an unmapped Windows error code
    (FakeScm(start="manual", fail=OSError(1061, "x")), "error", []),
])
def test_reconcile(services, scm, result, applied):
    log = ListLog()
    m = StartTypeManager(scm, services.settings, log)
    assert m.reconcile() == result and scm.applied == applied
    assert [(c, f["event"], f["result"], f["desired"]) for c, _, f in log.events] == [
        ("system", "service.start_type", result, "delayed-auto")
    ]


def test_a_disabled_service_reads_as_disabled_and_is_never_re_enabled(services):
    # plan review minor 17: an admin who disabled the service (incident response) must not see "manual,
    # in sync", and saving auto/delayed-auto must not silently enable it again
    log = ListLog()
    scm = FakeScm(start="disabled")
    m = StartTypeManager(scm, services.settings, log)
    assert m.reconcile() == "disabled" and m.reconcile("auto") == "disabled" and scm.applied == []
    assert [f["result"] for _c, _t, f in log.events] == ["disabled", "disabled"]
    assert log.events[0][2]["current"] == "disabled"
    st = m.status()
    assert (st["installed"], st["start_type"], st["in_sync"]) == (True, "disabled", False)


async def test_put_start_type_on_a_disabled_service_is_audited_and_not_applied(local_client, services):
    scm = FakeScm(start="disabled"); services.start_type.configurator = scm
    await bootstrap(local_client); await login(local_client, services)
    r = await local_client.put("/api/settings", json={"service_start_type": "auto"}, headers={"X-CSRF-Token": local_client.csrf})
    assert r.status_code == 200 and scm.applied == []
    e = [x for x in await audit_events(services, "admin.audit") if x["action"] == "service_start_type_apply"]
    assert e[-1]["target"] == {"start_type": "auto", "result": "disabled"} and e[-1]["result"] == "error"
    assert (await local_client.get("/api/service")).json()["start_type"] == "disabled"


def test_reconcile_reports_the_start_type_before_applying(services):
    log = ListLog()
    StartTypeManager(FakeScm(start="manual"), services.settings, log).reconcile()
    assert log.events[0][2]["current"] == "manual"


def test_reconcile_with_a_failing_query_is_an_error(services):
    log = ListLog()
    scm = FakeScm(); scm.query_fail = PermissionError(5, "denied")
    assert StartTypeManager(scm, services.settings, log).reconcile() == "denied"
    scm.query_fail = OSError(1061, "x")
    assert StartTypeManager(scm, services.settings, log).reconcile() == "error"


def test_null_configurator_is_not_installed(services):
    m = StartTypeManager(NullConfigurator(), services.settings, ListLog())
    assert m.reconcile() == "not_installed"
    assert m.status() == {"installed": False, "running_as_service": False, "start_type": None,
                          "desired": "delayed-auto", "in_sync": False, "bundle": False}
    with pytest.raises(LookupError):
        NullConfigurator().apply("manual")


def test_status_says_whether_this_is_a_deployment_bundle(services, monkeypatch, tmp_path):
    # F20: the settings screen tells a development run (no service to install) from a bundle
    from app import bundle
    from app.winsvc import start_type as st_mod
    assert StartTypeManager(NullConfigurator(), services.settings, ListLog()).status()["bundle"] is False
    monkeypatch.setattr(st_mod, "find_bundle", lambda: bundle.Bundle(tmp_path, "runtime", "0.9.0"))
    m = StartTypeManager(NullConfigurator(), services.settings, ListLog())
    assert m.status()["bundle"] is True and m.bundled is True


async def test_put_start_type_applies_and_audits(local_client, services):
    scm = FakeScm(start="delayed-auto"); services.start_type.configurator = scm
    await bootstrap(local_client); await login(local_client, services)
    r = await local_client.put("/api/settings", json={"service_start_type": "manual"}, headers={"X-CSRF-Token": local_client.csrf})
    assert r.status_code == 200 and scm.applied == ["manual"]
    assert r.json()["service_start_type"] == "manual"
    e = [x for x in await audit_events(services, "admin.audit") if x["action"] == "service_start_type_apply"]
    assert e[-1]["target"] == {"start_type": "manual", "result": "applied"} and e[-1]["result"] == "ok"
    st = (await local_client.get("/api/service")).json()
    assert st == {"installed": True, "running_as_service": False, "start_type": "manual", "desired": "manual", "in_sync": True,
                  "bundle": False}


async def test_put_start_type_denied_by_the_scm_is_audited_as_error(local_client, services):
    scm = FakeScm(start="delayed-auto", fail=PermissionError(5, "denied")); services.start_type.configurator = scm
    await bootstrap(local_client); await login(local_client, services)
    r = await local_client.put("/api/settings", json={"service_start_type": "auto"}, headers={"X-CSRF-Token": local_client.csrf})
    assert r.status_code == 200 and r.json()["service_start_type"] == "auto"
    e = [x for x in await audit_events(services, "admin.audit") if x["action"] == "service_start_type_apply"]
    assert e[-1]["target"] == {"start_type": "auto", "result": "denied"} and e[-1]["result"] == "error"


async def test_put_without_a_start_type_change_does_not_touch_the_scm(local_client, services):
    scm = FakeScm(start="auto"); services.start_type.configurator = scm
    await bootstrap(local_client); await login(local_client, services)
    r = await local_client.put("/api/settings", json={"ping_interval_sec": 7}, headers={"X-CSRF-Token": local_client.csrf})
    assert r.status_code == 200 and scm.applied == []
    assert not [x for x in await audit_events(services, "admin.audit") if x["action"] == "service_start_type_apply"]


async def test_service_route_is_local_admin_only(local_client, external_client, services):
    await bootstrap(local_client)
    login_as(local_client, services, make_user(services, "d@x.com"), "local")
    assert (await local_client.get("/api/service")).status_code == 403
    assert (await external_client.get("/api/service")).status_code == 404


@pytest.mark.winlive
def test_scm_query_without_admin():
    assert ScmConfigurator("EventLog").query() in ("auto", "delayed-auto", "manual")
    assert ScmConfigurator("mcp-monitor-does-not-exist-7f3a").query() is None


@pytest.mark.winlive
def test_scm_preshutdown_timeout_without_admin():
    # read only (plan review I5): the service sets its own value when it starts, as LocalSystem
    assert ScmConfigurator("EventLog").preshutdown_timeout() > 0
    assert ScmConfigurator("mcp-monitor-does-not-exist-7f3a").preshutdown_timeout() is None
    with pytest.raises(LookupError):  # never set on a real service here: one that does not exist
        ScmConfigurator("mcp-monitor-does-not-exist-7f3a").set_preshutdown_timeout(60_000)


@pytest.mark.winlive
def test_scm_apply_without_admin_is_permission_error():
    with pytest.raises(PermissionError):
        ScmConfigurator("EventLog").apply("auto")
