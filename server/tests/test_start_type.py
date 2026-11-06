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
                          "desired": "delayed-auto", "in_sync": False}
    with pytest.raises(LookupError):
        NullConfigurator().apply("manual")


async def test_put_start_type_applies_and_audits(local_client, services):
    scm = FakeScm(start="delayed-auto"); services.start_type.configurator = scm
    await bootstrap(local_client); await login(local_client, services)
    r = await local_client.put("/api/settings", json={"service_start_type": "manual"}, headers={"X-CSRF-Token": local_client.csrf})
    assert r.status_code == 200 and scm.applied == ["manual"]
    assert r.json()["service_start_type"] == "manual"
    e = [x for x in await audit_events(services, "admin.audit") if x["action"] == "service_start_type_apply"]
    assert e[-1]["target"] == {"start_type": "manual", "result": "applied"} and e[-1]["result"] == "ok"
    st = (await local_client.get("/api/service")).json()
    assert st == {"installed": True, "running_as_service": False, "start_type": "manual", "desired": "manual", "in_sync": True}


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
def test_scm_apply_without_admin_is_permission_error():
    with pytest.raises(PermissionError):
        ScmConfigurator("EventLog").apply("auto")
