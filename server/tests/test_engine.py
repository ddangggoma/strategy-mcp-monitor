from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest

from app.monitor.engine import ActionInProgressError, Alert, McpEngine
from app.monitor.engine import RunScript as R
from app.monitor.engine import Transition as T
from app.monitor.models import CheckResult, Issue
from app.monitor.models import McpState as S
from tests.mcp_helpers import cfg

PD, UN, ND, WP = Issue.PROCESS_DOWN, Issue.UNRESPONSIVE, Issue.NETWORK_DOWN, Issue.WRONG_PROCESS


def ok(clock):
    return CheckResult(clock.now(), None, 5.0, 1, "python.exe", None)


def bad(clock, issue=PD):
    return CheckResult(clock.now(), issue, None, None, None, "connect")


def eng(clock, **kw):
    return McpEngine(cfg(**{"action_delay_sec": 30, "startup_grace_sec": 30, **kw}), clock)


def to_action(e, clock, issue=PD):
    e.on_check(bad(clock, issue))
    clock.advance(30)
    return e.on_check(bad(clock, issue))


# ---------------------------------------------------------------- plan scenarios


def test_suspect_then_back_to_healthy(clock):
    e = eng(clock)
    assert e.on_check(bad(clock)) == [T(S.HEALTHY, S.SUSPECT, PD)]
    assert e.on_check(ok(clock)) == [T(S.SUSPECT, S.HEALTHY, None)]


def test_accumulates_to_start(clock):
    e = eng(clock)
    t0 = clock.now()
    e.on_check(bad(clock))
    clock.advance(29)
    assert e.on_check(bad(clock)) == []
    assert e.snapshot().action_due_at == t0 + timedelta(seconds=30)
    clock.advance(1)
    assert e.on_check(bad(clock)) == [T(S.SUSPECT, S.ACTION, PD), R("start", "auto", "PROCESS_DOWN")]


def test_unresponsive_restarts(clock):
    assert to_action(eng(clock), clock, UN)[-1] == R("restart", "auto", "UNRESPONSIVE")


def test_grace_recovering_healthy(clock):
    e = eng(clock)
    run = to_action(e, clock)[-1]
    assert e.on_check(bad(clock)) == []  # checks are ignored during ACTION
    assert e.on_action_done(run, "ok") == []
    clock.advance(29)
    assert e.tick() == []
    clock.advance(1)
    assert e.tick() == [T(S.ACTION, S.RECOVERING, PD)]
    assert e.on_check(ok(clock)) == [T(S.RECOVERING, S.HEALTHY, None)]


def test_recovering_failure_back_to_suspect(clock):
    e = eng(clock, startup_grace_sec=0)
    run = to_action(e, clock)[-1]
    assert e.on_action_done(run, "ok") == [T(S.ACTION, S.RECOVERING, PD)]
    assert e.on_check(bad(clock)) == [T(S.RECOVERING, S.SUSPECT, PD)]


def test_budget_exhausted_stops_and_fails(clock):
    e = eng(clock, startup_grace_sec=0, max_auto_actions=2)
    for _ in range(2):
        run = to_action(e, clock)[-1]
        e.on_action_done(run, "ok")
    e.on_check(bad(clock))
    clock.advance(30)
    assert e.on_check(bad(clock)) == [T(S.SUSPECT, S.FAILED, PD), R("stop", "auto", "PROCESS_DOWN"), Alert(PD)]
    assert e.on_check(ok(clock)) == [] and e.state == S.FAILED


def test_budget_window_expires(clock):
    e = eng(clock, startup_grace_sec=0, max_auto_actions=1, window_sec=600)
    run = to_action(e, clock)[-1]
    e.on_action_done(run, "ok")
    e.on_check(ok(clock))
    clock.advance(601)
    assert to_action(e, clock)[-1] == R("start", "auto", "PROCESS_DOWN")


def test_non_ok_result_backs_off(clock):
    e = eng(clock)
    run = to_action(e, clock)[-1]
    assert e.on_action_done(run, "timeout") == [T(S.ACTION, S.SUSPECT, PD)]
    assert e.snapshot().action_due_at == clock.now() + timedelta(seconds=30)
    assert e.snapshot().auto_actions_in_window == 1


@pytest.mark.parametrize("kw,issue", [({}, ND), ({"auto_recovery": False}, PD)])
def test_alert_only(clock, kw, issue):
    e = eng(clock, **kw)
    e.on_check(bad(clock, issue))
    assert e.snapshot().action_due_at is None
    clock.advance(30)
    assert e.on_check(bad(clock, issue)) == [Alert(issue)]
    clock.advance(30)
    assert e.on_check(bad(clock, issue)) == [] and e.state == S.SUSPECT


def test_manual_stop_is_maintenance(clock):
    e = eng(clock)
    effects = e.manual("stop")
    assert effects == [T(S.HEALTHY, S.MAINTENANCE, None), R("stop", "manual", "manual")]
    with pytest.raises(ActionInProgressError):
        e.manual("start")
    e.on_action_done(effects[-1], "ok")
    assert e.on_check(bad(clock)) == [] and e.state == S.MAINTENANCE and e.snapshot().running is None


def test_manual_start_from_failed_and_non_ok(clock):
    e = eng(clock, startup_grace_sec=0, max_auto_actions=1)
    run = to_action(e, clock)[-1]
    e.on_action_done(run, "ok")
    stop = to_action(e, clock)[1]
    assert e.state == S.FAILED and stop == R("stop", "auto", "PROCESS_DOWN")
    e.on_action_done(stop, "ok")
    effects = e.manual("start")
    assert effects == [T(S.FAILED, S.ACTION, None), R("start", "manual", "manual")]
    assert e.on_action_done(effects[-1], "failed") == [T(S.ACTION, S.RECOVERING, None)]


def test_maintenance_toggle_and_initial(clock):
    e = eng(clock)
    assert e.set_maintenance(True) == [T(S.HEALTHY, S.MAINTENANCE, None)]
    assert e.set_maintenance(False) == [T(S.MAINTENANCE, S.HEALTHY, None)]
    assert eng(clock, maintenance=True).state == S.MAINTENANCE


def test_result_ignored_after_maintenance(clock):
    e = eng(clock)
    run = to_action(e, clock)[-1]
    e.set_maintenance(True)
    assert e.on_action_done(run, "ok") == [] and e.state == S.MAINTENANCE and e.snapshot().running is None


def test_boot(clock):
    e = eng(clock, autostart_on_boot=True)
    assert e.boot(bad(clock)) == [T(S.HEALTHY, S.ACTION, PD), R("start", "boot", "PROCESS_DOWN")]
    assert e.snapshot().auto_actions_in_window == 0
    assert eng(clock).boot(bad(clock)) == [T(S.HEALTHY, S.SUSPECT, PD)]
    assert eng(clock, autostart_on_boot=True, maintenance=True).boot(bad(clock)) == []


# ---------------------------------------------------------------- state builders


def in_state(clock, state, **kw):
    """Engine parked in `state` with no script running."""
    if state is S.HEALTHY:
        return eng(clock, **kw)
    if state is S.MAINTENANCE:
        e = eng(clock, **kw)
        e.set_maintenance(True)
        return e
    if state is S.SUSPECT:
        e = eng(clock, **kw)
        e.on_check(bad(clock))
        return e
    if state is S.ACTION:  # auto action done ok, inside the grace period
        e = eng(clock, startup_grace_sec=30, **{k: v for k, v in kw.items() if k != "startup_grace_sec"})
        e.on_action_done(to_action(e, clock)[-1], "ok")
        return e
    if state is S.RECOVERING:
        e = eng(clock, startup_grace_sec=0, **{k: v for k, v in kw.items() if k != "startup_grace_sec"})
        e.on_action_done(to_action(e, clock)[-1], "ok")
        return e
    assert state is S.FAILED
    e = eng(clock, startup_grace_sec=0, max_auto_actions=1)
    e.on_action_done(to_action(e, clock)[-1], "ok")
    stop = to_action(e, clock)[1]
    e.on_action_done(stop, "ok")
    return e


ALL_STATES = list(S)


def test_in_state_builder(clock):
    for s in ALL_STATES:
        e = in_state(clock, s)
        assert e.state is s and e.snapshot().running is None


# ---------------------------------------------------------------- table rows / boundaries


def test_suspect_boundary_is_inclusive_one_second_short_waits(clock):
    e = in_state(clock, S.SUSPECT)
    clock.advance(29.999)
    assert e.on_check(bad(clock)) == []
    clock.advance(0.001)
    assert e.on_check(bad(clock))[0] == T(S.SUSPECT, S.ACTION, PD)


def test_suspect_delay_measured_from_result_time(clock):
    e = in_state(clock, S.SUSPECT)
    since = clock.now()
    clock.advance(100)  # the caller is late; the result carries the probe time
    stale = CheckResult(since + timedelta(seconds=29), PD, None, None, None, "x")
    assert e.on_check(stale) == []
    fresh = CheckResult(since + timedelta(seconds=30), PD, None, None, None, "x")
    assert e.on_check(fresh)[0] == T(S.SUSPECT, S.ACTION, PD)


def test_suspect_issue_is_updated_and_picks_action_kind(clock):
    e = in_state(clock, S.SUSPECT)  # PROCESS_DOWN
    clock.advance(10)
    assert e.on_check(bad(clock, UN)) == []
    assert e.snapshot().issue is UN
    clock.advance(20)
    assert e.on_check(bad(clock, UN)) == [T(S.SUSPECT, S.ACTION, UN), R("restart", "auto", "UNRESPONSIVE")]


def test_action_running_snapshot_and_no_action_due(clock):
    e = eng(clock)
    run = to_action(e, clock)[-1]
    snap = e.snapshot()
    assert snap.state is S.ACTION and snap.running == run and snap.action_due_at is None
    assert snap.issue is PD and snap.alerted is False and snap.auto_actions_in_window == 1


def test_action_done_ok_grace_zero_clears_running_and_moves(clock):
    e = eng(clock, startup_grace_sec=0)
    run = to_action(e, clock)[-1]
    assert e.on_action_done(run, "ok") == [T(S.ACTION, S.RECOVERING, PD)]
    assert e.snapshot().running is None


@pytest.mark.parametrize("status", ["failed", "timeout", "error"])
@pytest.mark.parametrize("trigger_boot", [False, True])
def test_non_ok_auto_or_boot_backs_off_to_suspect(clock, status, trigger_boot):
    e = eng(clock, autostart_on_boot=True)
    run = e.boot(bad(clock))[-1] if trigger_boot else to_action(e, clock)[-1]
    assert run.trigger == ("boot" if trigger_boot else "auto")
    assert e.on_action_done(run, status) == [T(S.ACTION, S.SUSPECT, PD)]
    snap = e.snapshot()
    assert snap.action_due_at == clock.now() + timedelta(seconds=30)
    assert snap.running is None
    # full action_delay again: nothing at 29 s, action at exactly 30 s
    clock.advance(29)
    assert e.on_check(bad(clock)) == []
    clock.advance(1)
    assert e.on_check(bad(clock))[0] == T(S.SUSPECT, S.ACTION, PD)


@pytest.mark.parametrize("status", ["failed", "timeout", "error"])
def test_non_ok_manual_goes_recovering_whatever_the_status(clock, status):
    e = in_state(clock, S.SUSPECT)
    run = e.manual("restart")[-1]
    assert e.on_action_done(run, status) == [T(S.ACTION, S.RECOVERING, None)]


def test_manual_ok_uses_grace_then_recovering_with_no_issue(clock):
    e = in_state(clock, S.HEALTHY)
    run = e.manual("restart")[-1]
    assert e.on_action_done(run, "ok") == []
    clock.advance(30)
    assert e.tick() == [T(S.ACTION, S.RECOVERING, None)]


def test_failed_auto_actions_count_against_budget_with_backoff(clock):
    e = eng(clock, max_auto_actions=2)
    run = to_action(e, clock)[-1]
    e.on_action_done(run, "timeout")
    clock.advance(30)
    run = e.on_check(bad(clock))[-1]
    assert run.kind == "start"
    e.on_action_done(run, "failed")
    assert e.snapshot().auto_actions_in_window == 2
    clock.advance(30)
    assert e.on_check(bad(clock)) == [T(S.SUSPECT, S.FAILED, PD), R("stop", "auto", "PROCESS_DOWN"), Alert(PD)]


def test_tick_waits_for_script_even_after_grace_deadline(clock):
    e = eng(clock, startup_grace_sec=0)
    run = to_action(e, clock)[-1]
    clock.advance(1000)
    assert e.tick() == []  # still running
    assert e.on_action_done(run, "ok") == [T(S.ACTION, S.RECOVERING, PD)]


@pytest.mark.parametrize("state", [s for s in ALL_STATES if s is not S.ACTION])
def test_tick_is_a_no_op_outside_action(clock, state):
    e = in_state(clock, state)
    clock.advance(10_000)
    assert e.tick() == [] and e.state is state


def test_recovering_transitions(clock):
    e = in_state(clock, S.RECOVERING)
    assert e.on_check(ok(clock)) == [T(S.RECOVERING, S.HEALTHY, None)]
    e = in_state(clock, S.RECOVERING)
    clock.advance(500)
    bad_at = clock.now()
    assert e.on_check(bad(clock, UN)) == [T(S.RECOVERING, S.SUSPECT, UN)]
    assert e.snapshot().action_due_at == bad_at + timedelta(seconds=30)  # suspect_since = result.at


def test_healthy_ok_check_is_noop(clock):
    e = eng(clock)
    assert e.on_check(ok(clock)) == [] and e.state is S.HEALTHY


@pytest.mark.parametrize("issue", [ND, WP])
def test_alert_only_issues_alert_once_and_stay(clock, issue):
    e = in_state(clock, S.HEALTHY)
    e.on_check(bad(clock, issue))
    clock.advance(30)
    assert e.on_check(bad(clock, issue)) == [Alert(issue)]
    assert e.snapshot().alerted is True and e.snapshot().action_due_at is None
    clock.advance(300)
    assert e.on_check(bad(clock, issue)) == [] and e.state is S.SUSPECT


def test_alert_only_then_healthy_rearms_alert(clock):
    e = eng(clock)
    e.on_check(bad(clock, ND))
    clock.advance(30)
    assert e.on_check(bad(clock, ND)) == [Alert(ND)]
    assert e.on_check(ok(clock)) == [T(S.SUSPECT, S.HEALTHY, None)]
    assert e.snapshot().alerted is False
    e.on_check(bad(clock, ND))
    clock.advance(30)
    assert e.on_check(bad(clock, ND)) == [Alert(ND)]


def test_alert_only_just_before_delay_has_no_alert(clock):
    e = eng(clock)
    e.on_check(bad(clock, ND))
    clock.advance(29)
    assert e.on_check(bad(clock, ND)) == []


# -- auto-action budget window


def _spent_one_action(clock, window_sec=60):
    e = eng(clock, startup_grace_sec=0, max_auto_actions=1, window_sec=window_sec)
    stamp = clock.now() + timedelta(seconds=30)
    run = to_action(e, clock)[-1]
    e.on_action_done(run, "ok")
    e.on_check(ok(clock))
    assert e.state is S.HEALTHY and clock.now() == stamp
    return e, stamp


@pytest.mark.parametrize(
    "gap,expect_action",
    [(0, False), (29, False), (30, True), (31, True)],  # new action lands at stamp + gap + 30; window 60
)
def test_budget_window_boundary(clock, gap, expect_action):
    e, stamp = _spent_one_action(clock)
    clock.advance(gap)
    e.on_check(bad(clock))
    clock.advance(30)
    effects = e.on_check(bad(clock))
    if expect_action:
        assert effects == [T(S.SUSPECT, S.ACTION, PD), R("start", "auto", "PROCESS_DOWN")]
    else:
        assert effects == [T(S.SUSPECT, S.FAILED, PD), R("stop", "auto", "PROCESS_DOWN"), Alert(PD)]


def test_snapshot_window_count_rolls_off_exactly_at_window_sec(clock):
    e, stamp = _spent_one_action(clock)
    clock.advance(59)
    assert e.snapshot().auto_actions_in_window == 1
    clock.advance(1)
    assert clock.now() == stamp + timedelta(seconds=60)
    assert e.snapshot().auto_actions_in_window == 0


def test_boot_and_manual_actions_are_not_budgeted(clock):
    e = eng(clock, autostart_on_boot=True, startup_grace_sec=0, max_auto_actions=1)
    boot_run = e.boot(bad(clock))[-1]
    e.on_action_done(boot_run, "ok")
    e.on_check(ok(clock))
    manual_run = e.manual("restart")[-1]
    e.on_action_done(manual_run, "ok")
    e.on_check(ok(clock))
    assert e.snapshot().auto_actions_in_window == 0
    assert to_action(e, clock)[-1] == R("start", "auto", "PROCESS_DOWN")  # budget of 1 still intact


def test_reconfigure_applies_new_delay_window_and_budget(clock):
    e = eng(clock)
    t0 = clock.now()
    e.on_check(bad(clock))
    e.reconfigure(cfg(action_delay_sec=10, startup_grace_sec=30))
    assert e.config.action_delay_sec == 10
    assert e.snapshot().action_due_at == t0 + timedelta(seconds=10)
    clock.advance(10)
    assert e.on_check(bad(clock))[0] == T(S.SUSPECT, S.ACTION, PD)
    e.reconfigure(cfg(auto_recovery=False))  # does not move state by itself
    assert e.state is S.ACTION


# -- manual / maintenance


@pytest.mark.parametrize("state", [s for s in ALL_STATES])
@pytest.mark.parametrize("kind", ["start", "restart"])
def test_manual_start_restart_from_every_state(clock, state, kind):
    e = in_state(clock, state)
    before = e.state
    effects = e.manual(kind)
    expected: list = [] if before is S.ACTION else [T(before, S.ACTION, None)]
    assert effects == expected + [R(kind, "manual", "manual")]
    snap = e.snapshot()
    assert snap.state is S.ACTION and snap.issue is None and snap.running == R(kind, "manual", "manual")
    assert snap.action_due_at is None and snap.alerted is False


@pytest.mark.parametrize("state", [s for s in ALL_STATES])
def test_manual_stop_from_every_state(clock, state):
    e = in_state(clock, state)
    before = e.state
    effects = e.manual("stop")
    expected: list = [] if before is S.MAINTENANCE else [T(before, S.MAINTENANCE, None)]
    assert effects == expected + [R("stop", "manual", "manual")]
    assert e.state is S.MAINTENANCE and e.snapshot().issue is None


@pytest.mark.parametrize("kind", ["start", "stop", "restart"])
def test_manual_while_running_raises_and_changes_nothing(clock, kind):
    e = eng(clock)
    run = to_action(e, clock)[-1]
    snap = e.snapshot()
    with pytest.raises(ActionInProgressError):
        e.manual(kind)
    assert e.snapshot() == snap and snap.running == run


def test_manual_during_grace_replaces_pending_grace(clock):
    e = in_state(clock, S.ACTION)  # auto action finished, 30 s grace pending
    run = e.manual("restart")[-1]
    clock.advance(1000)
    assert e.tick() == []  # script running: the old grace deadline no longer applies
    assert e.on_action_done(run, "ok") == []  # a fresh grace begins
    clock.advance(29)
    assert e.tick() == []
    clock.advance(1)
    assert e.tick() == [T(S.ACTION, S.RECOVERING, None)]


def test_manual_stop_non_ok_still_maintenance(clock):
    e = eng(clock)
    run = e.manual("stop")[-1]
    assert e.on_action_done(run, "error") == [] and e.state is S.MAINTENANCE
    assert e.on_check(bad(clock)) == []
    assert e.snapshot().running is None


def test_manual_start_from_maintenance_then_healthy(clock):
    e = in_state(clock, S.MAINTENANCE, startup_grace_sec=0)
    run = e.manual("start")[-1]
    assert e.on_action_done(run, "ok") == [T(S.ACTION, S.RECOVERING, None)]
    assert e.on_check(ok(clock)) == [T(S.RECOVERING, S.HEALTHY, None)]


@pytest.mark.parametrize("state", ALL_STATES)
def test_set_maintenance_true_from_every_state(clock, state):
    e = in_state(clock, state)
    before = e.state
    effects = e.set_maintenance(True)
    assert effects == ([] if before is S.MAINTENANCE else [T(before, S.MAINTENANCE, None)])
    snap = e.snapshot()
    assert snap.state is S.MAINTENANCE and snap.issue is None and snap.action_due_at is None
    assert e.set_maintenance(True) == []


@pytest.mark.parametrize("state", [s for s in ALL_STATES if s is not S.MAINTENANCE])
def test_set_maintenance_false_outside_maintenance_is_noop(clock, state):
    e = in_state(clock, state)
    assert e.set_maintenance(False) == [] and e.state is state


def test_maintenance_leaves_failed_and_clears_alert(clock):
    e = in_state(clock, S.FAILED)
    assert e.set_maintenance(True) == [T(S.FAILED, S.MAINTENANCE, None)]
    assert e.set_maintenance(False) == [T(S.MAINTENANCE, S.HEALTHY, None)]


def test_maintenance_in_flight_script_keeps_lock_until_done(clock):
    e = eng(clock)
    run = to_action(e, clock)[-1]
    e.set_maintenance(True)
    with pytest.raises(ActionInProgressError):
        e.manual("start")
    e.on_action_done(run, "ok")
    assert e.manual("start")[-1] == R("start", "manual", "manual")


def test_set_maintenance_false_with_script_in_flight_ignores_late_result(clock):
    e = eng(clock)
    run = to_action(e, clock)[-1]
    e.set_maintenance(True)
    e.set_maintenance(False)
    assert e.state is S.HEALTHY
    assert e.on_action_done(run, "failed") == [] and e.state is S.HEALTHY


# -- FAILED stickiness


def test_failed_is_sticky_for_checks_and_ticks(clock):
    e = in_state(clock, S.FAILED)
    for _ in range(3):
        clock.advance(600)
        assert e.on_check(ok(clock)) == []
        assert e.on_check(bad(clock, UN)) == []
        assert e.tick() == []
    assert e.state is S.FAILED
    assert e.needs_issue_check() is False and e.needs_confirm() is False


def test_failed_stop_result_does_not_change_state(clock):
    e = eng(clock, startup_grace_sec=0, max_auto_actions=1)
    e.on_action_done(to_action(e, clock)[-1], "ok")
    stop = to_action(e, clock)[1]
    assert e.snapshot().running == stop
    with pytest.raises(ActionInProgressError):  # stop in flight blocks manual
        e.manual("start")
    assert e.on_action_done(stop, "timeout") == []
    assert e.state is S.FAILED and e.snapshot().running is None


# -- boot


def test_boot_autostart_budget_and_issue(clock):
    e = eng(clock, autostart_on_boot=True)
    e.boot(bad(clock))
    snap = e.snapshot()
    assert snap.state is S.ACTION and snap.issue is PD
    assert snap.running == R("start", "boot", "PROCESS_DOWN") and snap.auto_actions_in_window == 0


def test_boot_ok_ends_in_recovering_then_healthy(clock):
    e = eng(clock, autostart_on_boot=True, startup_grace_sec=0)
    run = e.boot(bad(clock))[-1]
    assert e.on_action_done(run, "ok") == [T(S.ACTION, S.RECOVERING, PD)]
    assert e.on_check(ok(clock)) == [T(S.RECOVERING, S.HEALTHY, None)]


@pytest.mark.parametrize("issue", [UN, ND, WP])
def test_boot_autostart_other_issues_behave_like_a_check(clock, issue):
    e = eng(clock, autostart_on_boot=True)
    assert e.boot(bad(clock, issue)) == [T(S.HEALTHY, S.SUSPECT, issue)]


def test_boot_ok_result_is_noop(clock):
    for flag in (True, False):
        e = eng(clock, autostart_on_boot=flag)
        assert e.boot(ok(clock)) == [] and e.state is S.HEALTHY


def test_boot_without_autostart_then_normal_path(clock):
    e = eng(clock)
    assert e.boot(bad(clock)) == [T(S.HEALTHY, S.SUSPECT, PD)]
    clock.advance(30)
    assert e.on_check(bad(clock))[-1] == R("start", "auto", "PROCESS_DOWN")


@pytest.mark.parametrize("state", [s for s in ALL_STATES if s is not S.HEALTHY])
def test_boot_outside_healthy_never_starts_a_boot_action(clock, state):
    e = in_state(clock, state, autostart_on_boot=True)
    effects = e.boot(bad(clock))
    assert not any(isinstance(x, R) and x.trigger == "boot" for x in effects)


# -- out-of-table inputs: ignored, never raise


@pytest.mark.parametrize("state", ALL_STATES)
@pytest.mark.parametrize("status", ["ok", "failed", "timeout", "error"])
def test_action_done_with_nothing_running_is_ignored(clock, state, status):
    e = in_state(clock, state)
    snap = e.snapshot()
    assert e.on_action_done(R("start", "auto", "PROCESS_DOWN"), status) == []
    assert e.snapshot() == snap


def test_action_done_for_a_different_run_is_ignored(clock):
    e = eng(clock)
    run = to_action(e, clock)[-1]
    snap = e.snapshot()
    assert e.on_action_done(R("restart", "auto", "PROCESS_DOWN"), "ok") == []
    assert e.snapshot() == snap
    assert e.on_action_done(run, "ok") == []  # the real one still settles
    assert e.snapshot().running is None


def test_action_done_twice_second_is_ignored(clock):
    e = eng(clock, startup_grace_sec=0)
    run = to_action(e, clock)[-1]
    assert e.on_action_done(run, "ok") == [T(S.ACTION, S.RECOVERING, PD)]
    assert e.on_action_done(run, "failed") == [] and e.state is S.RECOVERING


@pytest.mark.parametrize("state", [S.ACTION, S.FAILED, S.MAINTENANCE])
def test_checks_ignored_in_state_without_changes(clock, state):
    e = in_state(clock, state)
    snap = e.snapshot()
    assert e.on_check(bad(clock, UN)) == [] and e.on_check(ok(clock)) == []
    assert e.snapshot() == snap


def test_maintenance_initial_ignores_boot_and_checks(clock):
    e = eng(clock, maintenance=True, autostart_on_boot=True)
    assert e.boot(bad(clock)) == [] and e.on_check(bad(clock)) == [] and e.tick() == []
    assert e.state is S.MAINTENANCE


# -- polling flags & snapshot


@pytest.mark.parametrize(
    "state,issue_check,confirm",
    [
        (S.HEALTHY, True, False),
        (S.SUSPECT, False, True),
        (S.RECOVERING, False, True),
        (S.ACTION, False, False),
        (S.FAILED, False, False),
        (S.MAINTENANCE, False, False),
    ],
)
def test_needs_flags(clock, state, issue_check, confirm):
    e = in_state(clock, state)
    assert e.needs_issue_check() is issue_check
    assert e.needs_confirm() is confirm


def test_snapshot_state_since_tracks_state_changes_only(clock):
    e = eng(clock)
    t0 = clock.now()
    assert e.snapshot().state_since == t0
    clock.advance(5)
    e.on_check(ok(clock))
    assert e.snapshot().state_since == t0  # no change, no update
    e.on_check(bad(clock))
    assert e.snapshot().state_since == t0 + timedelta(seconds=5)
    clock.advance(5)
    e.on_check(bad(clock))  # SUSPECT -> SUSPECT
    assert e.snapshot().state_since == t0 + timedelta(seconds=5)


def test_snapshot_is_a_frozen_value(clock):
    e = eng(clock)
    snap = e.snapshot()
    e.on_check(bad(clock))
    assert snap.state is S.HEALTHY and e.snapshot().state is S.SUSPECT
    with pytest.raises(FrozenInstanceError):
        snap.state = S.FAILED  # type: ignore[misc]


def test_initial_state_follows_config(clock):
    assert eng(clock).state is S.HEALTHY
    e = eng(clock, maintenance=True)
    assert e.state is S.MAINTENANCE and e.needs_issue_check() is False


def test_manual_from_suspect_clears_issue_and_due(clock):
    e = in_state(clock, S.SUSPECT)
    assert e.snapshot().action_due_at is not None
    e.manual("start")
    snap = e.snapshot()
    assert snap.issue is None and snap.action_due_at is None


def test_engine_is_deterministic(clock):
    def drive():
        e = eng(clock, startup_grace_sec=0)
        out = [e.on_check(bad(clock))]
        clock.advance(30)
        out.append(e.on_check(bad(clock)))
        out.append(e.on_action_done(out[-1][-1], "ok"))
        return out, e.snapshot()

    a, snap_a = drive()
    clock.advance(-30)  # rewind the same clock: identical inputs
    b, snap_b = drive()
    assert a == b and snap_a.auto_actions_in_window == snap_b.auto_actions_in_window == 1


# ---------------------------------------------------------------- I2: single-flight actions


def test_no_second_action_while_first_runs_after_maintenance_toggle(clock):
    """Auto start running -> maintenance on/off -> checks fail past the delay: no second RunScript."""
    e = eng(clock)
    first = to_action(e, clock)[-1]
    assert first == R("start", "auto", "PROCESS_DOWN")
    e.set_maintenance(True); e.set_maintenance(False)
    assert e.state is S.HEALTHY and e.snapshot().running is first
    effects = e.on_check(bad(clock))
    for _ in range(4):
        clock.advance(30)
        effects += e.on_check(bad(clock))
    assert not any(isinstance(x, R) for x in effects) and e.state is S.SUSPECT
    assert e.snapshot().running is first
    assert e.on_action_done(first, "ok") == []  # settles the first run only; the state moved on
    assert e.snapshot().running is None
    clock.advance(1)
    assert [x for x in e.on_check(bad(clock)) if isinstance(x, R)] == [R("start", "auto", "PROCESS_DOWN")]


def test_no_failed_stop_while_a_run_is_in_flight(clock):
    """Budget exhausted while the old run still runs: no stop RunScript until it settles."""
    e = eng(clock, max_auto_actions=1)
    first = to_action(e, clock)[-1]
    e.set_maintenance(True); e.set_maintenance(False)
    e.on_check(bad(clock)); clock.advance(30)
    assert e.on_check(bad(clock)) == [] and e.state is S.SUSPECT and e.snapshot().running is first


def test_boot_does_not_start_while_a_run_is_in_flight(clock):
    e = eng(clock, autostart_on_boot=True)
    run = e.manual("start")[-1]
    e.set_maintenance(True); e.set_maintenance(False)
    assert not any(isinstance(x, R) for x in e.boot(bad(clock)))
    assert e.snapshot().running is run


def test_completion_matches_by_identity_not_value(clock):
    e = eng(clock)
    run = to_action(e, clock)[-1]
    snap = e.snapshot()
    assert e.on_action_done(R("start", "auto", "PROCESS_DOWN"), "ok") == []  # equal value, different run
    assert e.snapshot() == snap and e.snapshot().running is run
    assert e.on_action_done(run, "timeout") == [T(S.ACTION, S.SUSPECT, PD)]
