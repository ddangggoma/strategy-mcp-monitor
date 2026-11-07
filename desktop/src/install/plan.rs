//! The installer's "plan (step list) → run" path (Plan 5's `Add-Step`, `$Internal`, `$Conditions`,
//! `$AfterStep`, `Invoke-Plan`, `-DryRun`): a pure builder makes a [`Plan`], `--dry-run` prints it
//! as one JSON line, otherwise an [`Executor`] runs it step by step.

use serde::Serialize;
use std::io::Write;

/// One step: `cmd` is a System32 tool (`sc.exe`, `auditpol`, `reg`, `wevtutil`, `netsh`) or, when it
/// starts with `(`, an action of this program. `ok` are the exit codes that count as success;
/// `when` names a condition checked just before the step runs.
#[derive(Serialize, Clone, Debug, PartialEq)]
pub struct Step {
    pub id: String,
    pub cmd: String,
    pub args: Vec<String>,
    pub ok: Vec<i32>,
    pub when: Option<String>,
}

impl Step {
    /// A step that succeeds on exit code 0 and always runs.
    pub fn new(id: &str, cmd: &str, args: Vec<String>) -> Step {
        Step {
            id: id.to_string(),
            cmd: cmd.to_string(),
            args,
            ok: vec![0],
            when: None,
        }
    }

    pub fn ok(mut self, codes: &[i32]) -> Step {
        self.ok = codes.to_vec();
        self
    }

    pub fn when(mut self, condition: &str) -> Step {
        self.when = Some(condition.to_string());
        self
    }
}

/// The plan as `--dry-run` prints it (Plan 5's JSON shape; keys in field order).
#[derive(Serialize, Debug)]
pub struct Plan {
    pub script: String,
    pub version: Option<String>,
    pub layout: Option<String>,
    pub install_dir: Option<String>,
    pub data_root: Option<String>,
    pub service_mode: Option<String>,
    pub steps: Vec<Step>,
    pub notes: Vec<String>,
}

/// Why a step did not succeed.
#[derive(Debug, Clone, PartialEq)]
pub enum StepError {
    /// `(admin)` without administrator rights: [`ADMIN_MESSAGE`], exit 1, no `[실패]` line.
    NotAdmin,
    Failed(String),
}

/// Runs the steps of a [`Plan`]. The real one is `exec::RealExecutor`; tests use fakes.
pub trait Executor {
    fn condition(&mut self, when: &str) -> bool;
    fn internal(&mut self, step: &Step) -> Result<i32, StepError>;
    fn native(&mut self, cmd: &str, args: &[String]) -> Result<i32, StepError>;
    /// What follows a successful step (Plan 5's `$AfterStep`), only for [`AFTER_STEPS`].
    fn after(&mut self, id: &str) -> Result<(), StepError>;
}

pub const ADMIN_MESSAGE: &str = "관리자 권한으로 다시 실행하세요. (mcp-monitor.exe를 마우스 오른쪽 단추로 눌러 \"관리자 권한으로 실행\" 또는 관리자 PowerShell)";

/// The steps with a follow-up: after `stop_existing` (install) and `stop_service` (uninstall) the
/// service must have stopped within 60 s.
pub const AFTER_STEPS: &[&str] = &["stop_existing", "stop_service"];

/// `Invoke-Plan`: `[i/n] <id>` per step (`[i/n] <id>: 건너뜀 (<when> 아님)` when its condition is
/// false); stops at the first failure with `[실패] <id>: <why>` and 1, or [`ADMIN_MESSAGE`] and 1.
/// Returns 0 when every step succeeded.
pub fn run_plan(plan: &Plan, ex: &mut dyn Executor, out: &mut dyn Write) -> i32 {
    let n = plan.steps.len();
    let mut done: Vec<&str> = Vec::new();
    for (i, s) in plan.steps.iter().enumerate() {
        let i = i + 1;
        if let Some(when) = &s.when
            && !ex.condition(when)
        {
            let _ = writeln!(out, "[{i}/{n}] {}: 건너뜀 ({when} 아님)", s.id);
            continue;
        }
        let _ = writeln!(out, "[{i}/{n}] {}", s.id);
        let ran = if s.cmd.starts_with('(') {
            ex.internal(s)
        } else {
            ex.native(&s.cmd, &s.args)
        }
        .and_then(|code| {
            if s.ok.contains(&code) {
                Ok(())
            } else {
                Err(StepError::Failed(format!("종료 코드 {code}")))
            }
        });
        // The step's own command succeeded; only its follow-up can still fail.
        let ran_ok = ran.is_ok();
        let result = ran.and_then(|()| {
            if AFTER_STEPS.contains(&s.id.as_str()) {
                ex.after(&s.id)
            } else {
                Ok(())
            }
        });
        match result {
            Ok(()) => {}
            Err(StepError::NotAdmin) => {
                let _ = writeln!(out, "{ADMIN_MESSAGE}");
                let _ = out.flush();
                return 1;
            }
            Err(StepError::Failed(why)) => {
                let _ = writeln!(out, "[실패] {}: {why}", s.id);
                // `sc stop` was sent but the wait for it failed (re-review nit 4): the service may
                // still finish stopping, so it counts as stopped.
                let stop_sent = ran_ok && s.id == "stop_existing";
                recover_install(plan, &done, &s.id, stop_sent, ex, out);
                let _ = out.flush();
                return 1;
            }
        }
        done.push(&s.id);
        let _ = out.flush();
    }
    0
}

/// Review item 4: an install that stopped the running service (`stop_existing`) and then failed
/// before `service_start` must not leave it down without a word. Before `swap_install_dir` the
/// earlier install is whole, so its service is started again (`sc.exe start mcp-monitor`); after
/// it, the earlier binPath may name a file that moved to `<I>.old` (an upgrade from 1.0.0), so
/// the line says how to recover instead. Each outcome is one `[복구] …` line after `[실패]`.
/// `stop_sent`: `stop_existing` itself failed after `sc stop` was sent (its wait for the stop did
/// not end in time), which counts as a stopped service too (re-review nit 4).
fn recover_install(
    plan: &Plan,
    done: &[&str],
    failed: &str,
    stop_sent: bool,
    ex: &mut dyn Executor,
    out: &mut dyn Write,
) {
    // A failed `service_start` / `wait_ready` is OPERATIONS ③ 5 (the new version may already have
    // migrated the database): the earlier version is not started again.
    if plan.script != "install"
        || !(done.contains(&"stop_existing") || stop_sent)
        || failed == "service_start"
        || done.contains(&"service_start")
    {
        return;
    }
    let service = crate::install::host::SERVICE_NAME;
    if !done.contains(&"swap_install_dir") {
        let start = ex.native("sc.exe", &["start".to_string(), service.to_string()]);
        let _ = match start {
            Ok(0 | 1056) => writeln!(
                out,
                "[복구] 이전 버전의 서비스를 다시 시작했습니다(sc.exe start {service})."
            ),
            Ok(code) => writeln!(
                out,
                "[복구] 이전 버전의 서비스를 다시 시작하지 못했습니다(종료 코드 {code}). 원인을 고친 뒤 sc.exe start {service} 로 시작하거나, 같은 mcp-monitor.exe를 관리자 권한으로 다시 실행하세요."
            ),
            Err(StepError::Failed(why)) => writeln!(
                out,
                "[복구] 이전 버전의 서비스를 다시 시작하지 못했습니다({why}). 원인을 고친 뒤 sc.exe start {service} 로 시작하거나, 같은 mcp-monitor.exe를 관리자 권한으로 다시 실행하세요."
            ),
            Err(StepError::NotAdmin) => Ok(()),
        };
        return;
    }
    let old = plan
        .install_dir
        .as_deref()
        .map_or_else(|| "<설치 폴더>.old".to_string(), |i| format!("{i}.old"));
    let _ = writeln!(
        out,
        "[복구] 서비스가 멈춰 있습니다. 원인을 고친 뒤 같은 mcp-monitor.exe를 관리자 권한으로 다시 실행하세요(복구 설치). 이전 설치는 {old} 에 있습니다."
    );
}

/// `-DryRun`: each note as `참고: <note>` on `err`, the plan as one compact JSON line on `out`, 0.
pub fn print_dry_run(plan: &Plan, out: &mut dyn Write, err: &mut dyn Write) -> i32 {
    for note in &plan.notes {
        let _ = writeln!(err, "참고: {note}");
    }
    let json = serde_json::to_string(plan).expect("a plan always serializes");
    let _ = writeln!(out, "{json}");
    let _ = out.flush();
    0
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn st(id: &str, cmd: &str, ok: &[i32], when: Option<&str>) -> Step {
        Step {
            id: id.into(),
            cmd: cmd.into(),
            args: vec![],
            ok: ok.to_vec(),
            when: when.map(String::from),
        }
    }
    fn plan(steps: Vec<Step>) -> Plan {
        Plan {
            script: "install".into(),
            version: Some("1.1.0".into()),
            layout: Some("pyinstaller".into()),
            install_dir: None,
            data_root: None,
            service_mode: Some("create".into()),
            steps,
            notes: vec!["n1".into()],
        }
    }

    #[derive(Default)]
    struct FakeExec {
        admin: bool,
        log: Vec<String>,
        codes: HashMap<String, i32>,
        conds: HashMap<String, bool>,
    }
    impl Executor for FakeExec {
        fn condition(&mut self, when: &str) -> bool {
            *self.conds.get(when).unwrap_or(&true)
        }
        fn internal(&mut self, s: &Step) -> Result<i32, StepError> {
            self.log.push(s.id.clone());
            if s.cmd == "(admin)" && !self.admin {
                return Err(StepError::NotAdmin);
            }
            Ok(*self.codes.get(&s.id).unwrap_or(&0))
        }
        fn native(&mut self, cmd: &str, args: &[String]) -> Result<i32, StepError> {
            self.log.push(cmd.into());
            let full = format!("{cmd} {}", args.join(" "));
            Ok(*self
                .codes
                .get(&full)
                .or_else(|| self.codes.get(cmd))
                .unwrap_or(&0))
        }
        fn after(&mut self, id: &str) -> Result<(), StepError> {
            self.log.push(format!("after {id}"));
            Ok(())
        }
    }

    #[test]
    fn require_admin_comes_first_and_stops_without_admin() {
        let p = plan(vec![
            st("require_admin", "(admin)", &[0], None),
            st("x", "sc.exe", &[0], None),
        ]);
        let mut ex = FakeExec::default();
        let mut out = Vec::new();
        assert_eq!(run_plan(&p, &mut ex, &mut out), 1);
        assert_eq!(ex.log, ["require_admin"]);
        let text = String::from_utf8(out).unwrap();
        assert!(
            text.contains(ADMIN_MESSAGE) && !text.contains("[실패]"),
            "{text}"
        );
    }

    #[test]
    fn run_plan_skips_false_conditions_and_stops_at_the_first_failure() {
        let p = plan(vec![
            st("a", "(write-json)", &[0], None),
            st("b", "netsh", &[0], Some("x")),
            st("c", "sc.exe", &[0, 1062], None),
            st("d", "auditpol", &[0], None),
            st("e", "(wait)", &[0], None),
        ]);
        let mut ex = FakeExec {
            admin: true,
            ..Default::default()
        };
        ex.conds.insert("x".into(), false);
        ex.codes.insert("sc.exe".into(), 1062);
        ex.codes.insert("auditpol".into(), 5);
        let mut out = Vec::new();
        assert_eq!(run_plan(&p, &mut ex, &mut out), 1);
        assert_eq!(ex.log, ["a", "sc.exe", "auditpol"]);
        let text = String::from_utf8(out).unwrap();
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(
            lines,
            [
                "[1/5] a",
                "[2/5] b: 건너뜀 (x 아님)",
                "[3/5] c",
                "[4/5] d",
                "[실패] d: 종료 코드 5"
            ]
        );
    }

    #[test]
    fn dry_run_prints_one_compact_json_line_and_notes_on_stderr() {
        let p = plan(vec![st("require_admin", "(admin)", &[0], None)]);
        let (mut out, mut err) = (Vec::new(), Vec::new());
        assert_eq!(print_dry_run(&p, &mut out, &mut err), 0);
        let text = String::from_utf8(out).unwrap();
        assert_eq!(text.matches('\n').count(), 1);
        assert!(text.starts_with(r#"{"script":"install","version":"1.1.0","layout":"pyinstaller","install_dir":null,"data_root":null,"service_mode":"create","steps":[{"id":"require_admin","cmd":"(admin)","args":[],"ok":[0],"when":null}],"notes":["n1"]}"#), "{text}");
        assert_eq!(String::from_utf8(err).unwrap(), "참고: n1\n");
    }

    // --- additions beyond the plan text -----------------------------------------------------------

    /// An executor whose answers are scripted per step id: internal and native failures and an
    /// `after` hook that fails.
    struct Scripted {
        log: Vec<String>,
        fail_internal: Option<String>,
        fail_after: bool,
    }
    impl Executor for Scripted {
        fn condition(&mut self, _when: &str) -> bool {
            true
        }
        fn internal(&mut self, s: &Step) -> Result<i32, StepError> {
            self.log.push(format!("internal {}", s.id));
            match &self.fail_internal {
                Some(m) => Err(StepError::Failed(m.clone())),
                None => Ok(0),
            }
        }
        fn native(&mut self, cmd: &str, args: &[String]) -> Result<i32, StepError> {
            self.log.push(format!("native {cmd} {}", args.join(" ")));
            Ok(1062)
        }
        fn after(&mut self, id: &str) -> Result<(), StepError> {
            self.log.push(format!("after {id}"));
            if self.fail_after {
                Err(StepError::Failed("서비스가 멈추지 않았습니다".into()))
            } else {
                Ok(())
            }
        }
    }

    #[test]
    fn a_whole_plan_runs_each_step_once_and_after_follows_success() {
        let mut stop = st(
            "stop_existing",
            "sc.exe",
            &[0, 1062],
            Some("service_exists"),
        );
        stop.args = vec!["stop".into(), "mcp-monitor".into()];
        let p = plan(vec![st("require_admin", "(admin)", &[0], None), stop]);
        let mut ex = Scripted {
            log: vec![],
            fail_internal: None,
            fail_after: false,
        };
        let mut out = Vec::new();
        assert_eq!(run_plan(&p, &mut ex, &mut out), 0);
        // Only the steps with a follow-up (`stop_existing`: wait for the service to stop) get `after`.
        assert_eq!(
            ex.log,
            [
                "internal require_admin",
                "native sc.exe stop mcp-monitor",
                "after stop_existing"
            ]
        );
        assert_eq!(
            String::from_utf8(out).unwrap(),
            "[1/2] require_admin\n[2/2] stop_existing\n"
        );
    }

    #[test]
    fn failed_internal_steps_and_after_hooks_print_one_failure_line() {
        let p = plan(vec![
            st("install_state", "(write-state)", &[0], None),
            st("z", "sc.exe", &[0], None),
        ]);
        let mut ex = Scripted {
            log: vec![],
            fail_internal: Some("디스크가 가득 찼습니다".into()),
            fail_after: false,
        };
        let mut out = Vec::new();
        assert_eq!(run_plan(&p, &mut ex, &mut out), 1);
        assert_eq!(
            String::from_utf8(out).unwrap(),
            "[1/2] install_state\n[실패] install_state: 디스크가 가득 찼습니다\n"
        );

        let mut p = plan(vec![
            st("stop_existing", "sc.exe", &[1062], None),
            st("z", "sc.exe", &[0], None),
        ]);
        p.script = "uninstall".into();
        let mut ex = Scripted {
            log: vec![],
            fail_internal: None,
            fail_after: true,
        };
        let mut out = Vec::new();
        assert_eq!(run_plan(&p, &mut ex, &mut out), 1);
        assert_eq!(ex.log.len(), 2, "{:?}", ex.log);
        assert_eq!(
            String::from_utf8(out).unwrap(),
            "[1/2] stop_existing\n[실패] stop_existing: 서비스가 멈추지 않았습니다\n"
        );
    }

    /// Re-review nit 4: `sc stop` was sent but the wait for the stop ran out. The service may still
    /// finish stopping, so the install tries to start it again and says how it went; a `sc stop`
    /// that itself failed stopped nothing, so nothing is said.
    #[test]
    fn a_stop_whose_wait_runs_out_gets_a_recovery_line() {
        let p = upgrade();
        let mut ex = Scripted {
            log: vec![],
            fail_internal: None,
            fail_after: true,
        };
        let mut out = Vec::new();
        assert_eq!(run_plan(&p, &mut ex, &mut out), 1);
        assert_eq!(
            ex.log,
            [
                "internal require_admin",
                "native sc.exe stop mcp-monitor",
                "after stop_existing",
                "native sc.exe start mcp-monitor"
            ]
        );
        let text = String::from_utf8(out).unwrap();
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(
            lines[2..],
            [
                "[실패] stop_existing: 서비스가 멈추지 않았습니다",
                "[복구] 이전 버전의 서비스를 다시 시작하지 못했습니다(종료 코드 1062). 원인을 고친 뒤 sc.exe start mcp-monitor 로 시작하거나, 같은 mcp-monitor.exe를 관리자 권한으로 다시 실행하세요."
            ]
        );

        let (code, lines, log) = run_failing(&upgrade(), "sc.exe stop mcp-monitor", 0);
        assert_eq!(code, 1);
        assert_eq!(
            lines.last().unwrap(),
            "[실패] stop_existing: 종료 코드 9",
            "{lines:?}"
        );
        assert_eq!(log, ["require_admin", "sc.exe"]);
    }

    /// An upgrade-shaped install plan: the service is stopped at step 2, the folders are swapped at
    /// step 4, the service starts again at step 6.
    fn upgrade() -> Plan {
        let mut p = plan(vec![
            st("require_admin", "(admin)", &[0], None),
            Step {
                args: vec!["stop".into(), "mcp-monitor".into()],
                ..st(
                    "stop_existing",
                    "sc.exe",
                    &[0, 1062],
                    Some("service_exists"),
                )
            },
            st("stop_apps", "(stop-apps)", &[0], None),
            st("swap_install_dir", "(swap)", &[0], None),
            st("secure_data_root", "(secure-data-root)", &[0], None),
            Step {
                args: vec!["start".into(), "mcp-monitor".into()],
                ..st("service_start", "sc.exe", &[0, 1056], None)
            },
            st("wait_ready", "(wait)", &[0], None),
        ]);
        p.install_dir = Some(r"C:\Program Files\MCP Monitor".into());
        p
    }

    fn run_failing(p: &Plan, failing: &str, sc_code: i32) -> (i32, Vec<String>, Vec<String>) {
        let mut ex = FakeExec {
            admin: true,
            ..Default::default()
        };
        if failing == "service_start" {
            ex.codes.insert("sc.exe start mcp-monitor".into(), 9);
        } else {
            ex.codes.insert(failing.into(), 9);
            ex.codes.insert("sc.exe start mcp-monitor".into(), sc_code);
        }
        let mut out = Vec::new();
        let code = run_plan(p, &mut ex, &mut out);
        let lines = String::from_utf8(out)
            .unwrap()
            .lines()
            .map(String::from)
            .collect();
        (code, lines, ex.log)
    }

    /// Review item 4: a failure after the service was stopped and before the folders were swapped
    /// leaves the earlier install whole: its service is started again.
    #[test]
    fn a_failed_upgrade_before_the_swap_restarts_the_earlier_service() {
        let (code, lines, log) = run_failing(&upgrade(), "stop_apps", 0);
        assert_eq!(code, 1);
        assert_eq!(
            lines[3..],
            [
                "[실패] stop_apps: 종료 코드 9",
                "[복구] 이전 버전의 서비스를 다시 시작했습니다(sc.exe start mcp-monitor)."
            ]
        );
        assert_eq!(
            log,
            [
                "require_admin",
                "sc.exe",
                "after stop_existing",
                "stop_apps",
                "sc.exe"
            ]
        );
        // The restart itself fails: the exact commands to run by hand.
        let (_, lines, _) = run_failing(&upgrade(), "stop_apps", 1053);
        assert_eq!(
            lines[4],
            "[복구] 이전 버전의 서비스를 다시 시작하지 못했습니다(종료 코드 1053). 원인을 고친 뒤 sc.exe start mcp-monitor 로 시작하거나, 같은 mcp-monitor.exe를 관리자 권한으로 다시 실행하세요."
        );
    }

    /// After the swap the earlier binPath may name a file that moved to `<I>.old` (a 1.0.0
    /// upgrade): no restart, but the way back.
    #[test]
    fn a_failed_upgrade_after_the_swap_says_how_to_recover() {
        let (code, lines, log) = run_failing(&upgrade(), "secure_data_root", 0);
        assert_eq!(code, 1);
        assert_eq!(
            lines[5..],
            [
                "[실패] secure_data_root: 종료 코드 9",
                r"[복구] 서비스가 멈춰 있습니다. 원인을 고친 뒤 같은 mcp-monitor.exe를 관리자 권한으로 다시 실행하세요(복구 설치). 이전 설치는 C:\Program Files\MCP Monitor.old 에 있습니다."
            ]
        );
        assert_eq!(
            log.iter().filter(|c| *c == "sc.exe").count(),
            1,
            "no start: {log:?}"
        );
    }

    /// No recovery line when the service was never stopped (it did not exist, or the failure came
    /// first), when the service start itself failed (OPERATIONS ③ 5), and for other plans.
    #[test]
    fn nothing_to_recover_otherwise() {
        let (_, lines, _) = run_failing(&upgrade(), "require_admin", 0);
        assert!(!lines.iter().any(|l| l.starts_with("[복구]")), "{lines:?}");
        let mut ex = FakeExec {
            admin: true,
            ..Default::default()
        };
        ex.conds.insert("service_exists".into(), false);
        ex.codes.insert("stop_apps".into(), 9);
        let mut out = Vec::new();
        assert_eq!(run_plan(&upgrade(), &mut ex, &mut out), 1);
        assert!(!String::from_utf8(out).unwrap().contains("[복구]"));
        let (_, lines, _) = run_failing(&upgrade(), "service_start", 0);
        assert_eq!(lines.last().unwrap(), "[실패] service_start: 종료 코드 9");
        let mut p = upgrade();
        p.script = "uninstall".into();
        let (_, lines, _) = run_failing(&p, "stop_apps", 0);
        assert_eq!(lines.last().unwrap(), "[실패] stop_apps: 종료 코드 9");
    }

    #[test]
    fn dry_run_without_notes_writes_nothing_on_stderr_and_admin_message_is_the_plan_text() {
        let mut p = plan(vec![]);
        p.notes.clear();
        let (mut out, mut err) = (Vec::new(), Vec::new());
        assert_eq!(print_dry_run(&p, &mut out, &mut err), 0);
        assert!(err.is_empty());
        assert!(
            String::from_utf8(out)
                .unwrap()
                .ends_with("\"steps\":[],\"notes\":[]}\n")
        );
        assert_eq!(
            ADMIN_MESSAGE,
            "관리자 권한으로 다시 실행하세요. (mcp-monitor.exe를 마우스 오른쪽 단추로 눌러 \"관리자 권한으로 실행\" 또는 관리자 PowerShell)"
        );
    }
}
