//! `RealExecutor`: runs a plan on this PC (Plan 5's `$Internal`, `$Conditions`, `$AfterStep` and
//! `Invoke-Native`). System32 tools go through a [`Runner`] so tests never start one for real;
//! administrator rights and the service come from the [`Host`], registry writes go through a
//! [`Registry`]. Task 8 adds the uninstall actions that are still `아직 구현되지 않았습니다`.

use crate::install::acl::{ADMINISTRATORS, SYSTEM, initialize_data_root, kst_now};
use crate::install::audit::restore_registry;
use crate::install::host::{Host, SERVICE_NAME};
use crate::install::paths::is_inside;
use crate::install::plan::{Executor, Plan, Step, StepError};
use crate::install::procs::stop_apps;
use crate::install::registry::{Registry, parse_reg_value};
use crate::install::shortcut::create_shortcut;
use crate::install::stage::{
    PayloadSource, StdFs, remove_old, running_inside_problem, stage, swap,
};
use serde_json::Value;
use std::io::{self, Write};
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

/// `CREATE_NO_WINDOW`: a tool started from the GUI-subsystem exe never opens a console window.
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// Starts a System32 tool and returns its exit code. `quiet`: its output is thrown away (a
/// condition's query), otherwise it shares ours.
pub trait Runner {
    fn run(&mut self, cmd: &str, args: &[String], quiet: bool) -> io::Result<i32>;
}

/// `Invoke-Native`: the tool by its absolute System32 path (never the current folder or `PATH`),
/// `.exe` added when missing; arguments quoted by Rust's MSVCRT rules (the same as
/// `cli::quote_arg`, Task 4 `quoting_survives_command_line_to_argv`).
pub struct SystemRunner;

/// The absolute System32 path of tool `cmd` (`auditpol` → `…\System32\auditpol.exe`).
pub fn tool_path(cmd: &str) -> PathBuf {
    if cmd.to_ascii_lowercase().ends_with(".exe") {
        crate::winutil::system_tool(cmd)
    } else {
        crate::winutil::system_tool(&format!("{cmd}.exe"))
    }
}

impl Runner for SystemRunner {
    fn run(&mut self, cmd: &str, args: &[String], quiet: bool) -> io::Result<i32> {
        if cmd.is_empty() || cmd.contains(['\\', '/', ':']) || cmd.contains("..") {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!("System32 도구 이름이 아닙니다: {cmd}"),
            ));
        }
        let mut c = Command::new(tool_path(cmd));
        c.args(args).creation_flags(CREATE_NO_WINDOW);
        if quiet {
            c.stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null());
        }
        let status = c.status()?;
        Ok(status.code().unwrap_or(-1))
    }
}

fn spawn_error(cmd: &str, e: io::Error) -> StepError {
    StepError::Failed(format!("{cmd} 을(를) 실행하지 못했습니다: {e}"))
}

/// The real executor of one plan. `out` gets the lines an action prints itself.
pub struct RealExecutor<'a, R: Runner, W: Write> {
    host: &'a dyn Host,
    pub runner: R,
    pub out: W,
    /// `install` or `audit-policy`: the marker's `created_by`.
    script: String,
    data_root: Option<PathBuf>,
    install_dir: Option<PathBuf>,
    /// `name=MCP Monitor (<EP>)` of the plan's `firewall` step.
    firewall_rule: Option<String>,
    /// How long `stop_existing` waits for the service to stop.
    pub stop_wait: Duration,
    /// The data root's owner and full-control SIDs (`initialize_data_root`): Administrators and
    /// SYSTEM + Administrators. Tests without admin rights put this account there (Y18).
    pub data_root_owner: String,
    pub data_root_sids: Vec<String>,
    /// `(registry-set)` writes here: the real registry, except in unit tests (a `FakeRegistry`,
    /// so no test can write HKLM even on the elevated CI runner).
    pub registry: Box<dyn Registry + 'a>,
    /// This exe, copied into the install folder by `(stage)` (`None`: Windows could not say).
    pub self_exe: Option<PathBuf>,
    /// What `(stage)` extracts (`None`: the payload embedded in this exe).
    pub payload: Option<PayloadSource>,
}

#[cfg(not(test))]
fn default_registry<'a>() -> Box<dyn Registry + 'a> {
    Box::new(crate::install::registry::WinRegistry)
}

#[cfg(test)]
fn default_registry<'a>() -> Box<dyn Registry + 'a> {
    Box::new(crate::install::registry::FakeRegistry::default())
}

/// `(check-os)` (Y33): warnings only, the install goes on. A Home edition (the caption says
/// `Home`, or SKU 98–101) is no RDP host; an install folder outside Program Files may be writable
/// by ordinary users; without the WebView2 runtime the app and notice windows cannot open.
pub fn check_os_warnings(
    caption: &str,
    sku: u32,
    install_dir: &Path,
    program_files: &Path,
    webview2: Option<&str>,
) -> Vec<String> {
    let mut out = Vec::new();
    if caption.contains("Home") || (98..=101).contains(&sku) {
        out.push(format!(
            "경고: {caption}은(는) RDP 호스트가 아니어서 세션 수집이 동작하지 않습니다. 설치는 계속합니다."
        ));
    }
    if !is_inside(install_dir, program_files) {
        out.push(format!(
            "경고: {} 은(는) Program Files 밖입니다. 서비스(SYSTEM)가 이 폴더의 프로그램을 실행하므로 일반 사용자가 쓸 수 없는 폴더여야 합니다.",
            install_dir.display()
        ));
    }
    if webview2.is_none_or(|v| v.trim().is_empty() || v.trim() == "0.0.0.0") {
        out.push("경고: WebView2 런타임이 없습니다. 관리 화면 창과 고지 창이 열리지 않습니다(https://go.microsoft.com/fwlink/p/?LinkId=2124703 에서 설치).".into());
    }
    out
}

impl<'a, R: Runner, W: Write> RealExecutor<'a, R, W> {
    pub fn new(plan: &Plan, host: &'a dyn Host, runner: R, out: W) -> Self {
        let firewall_rule = plan
            .steps
            .iter()
            .find(|s| s.id == "firewall")
            .and_then(|s| s.args.iter().find(|a| a.starts_with("name=")).cloned());
        RealExecutor {
            host,
            runner,
            out,
            script: plan.script.clone(),
            data_root: plan.data_root.as_ref().map(PathBuf::from),
            install_dir: plan.install_dir.as_ref().map(PathBuf::from),
            firewall_rule,
            stop_wait: Duration::from_secs(60),
            data_root_owner: ADMINISTRATORS.to_string(),
            data_root_sids: vec![SYSTEM.to_string(), ADMINISTRATORS.to_string()],
            registry: default_registry(),
            self_exe: std::env::current_exe().ok(),
            payload: None,
        }
    }

    /// SYSTEM, Administrators and the installing account: who may own the data root and the
    /// install tree.
    fn owners(&self) -> [String; 3] {
        [
            SYSTEM.to_string(),
            ADMINISTRATORS.to_string(),
            self.host.user_sid(),
        ]
    }

    /// `(check-os)`: prints the warnings of [`check_os_warnings`] for install folder `inst`.
    fn check_os(&mut self, inst: &str) -> Result<i32, StepError> {
        let (caption, sku) = self.host.os_edition();
        let program_files = self.host.env().get("ProgramFiles").unwrap_or_default();
        let webview2 = self.host.webview2_version();
        for line in check_os_warnings(
            &caption,
            sku,
            Path::new(inst),
            Path::new(&program_files),
            webview2.as_deref(),
        ) {
            let _ = writeln!(self.out, "{line}");
        }
        Ok(0)
    }

    /// `(stage) <I>.staging <I>`: refused when this exe runs from the install folder (F06).
    fn stage_payload(&mut self, staging: &str, inst: &str) -> Result<i32, StepError> {
        let Some(exe) = self.self_exe.clone() else {
            return Err(StepError::Failed(
                "이 실행 파일의 위치를 알 수 없습니다".into(),
            ));
        };
        let version = self.host.payload().version;
        if let Some(why) = running_inside_problem(&exe, Path::new(inst), &version) {
            return Err(StepError::Failed(why));
        }
        let src = self.payload.take().unwrap_or_else(PayloadSource::embedded);
        let written = stage(Path::new(staging), &src, &exe).map_err(StepError::Failed)?;
        let _ = writeln!(
            self.out,
            "  {staging} 에 {:.1} MB를 풀었습니다.",
            written as f64 / 1_048_576.0
        );
        Ok(0)
    }

    /// `(registry-set) <key> <Name=REG_…:value>…`: every value is checked before any is written.
    fn registry_set(&mut self, step: &Step) -> Result<i32, StepError> {
        let key = need(step, 0)?;
        let values = step.args[1..]
            .iter()
            .map(|v| parse_reg_value(v))
            .collect::<Result<Vec<_>, _>>()
            .map_err(StepError::Failed)?;
        self.registry
            .set_values(key, &values)
            .map(|()| 0)
            .map_err(StepError::Failed)
    }

    /// `<D>\data\<name>` exists.
    fn data_file_exists(&self, name: &str) -> bool {
        self.data_root
            .as_ref()
            .is_some_and(|d| d.join("data").join(name).exists())
    }

    /// `netsh advfirewall firewall show rule name=…` fails: the rule is not there yet (`netsh add
    /// rule` would add a duplicate on every reinstall).
    fn firewall_rule_missing(&mut self) -> bool {
        let Some(rule) = self.firewall_rule.clone() else {
            return true;
        };
        let args: Vec<String> = ["advfirewall", "firewall", "show", "rule"]
            .iter()
            .map(|s| s.to_string())
            .chain([rule])
            .collect();
        self.runner
            .run("netsh", &args, true)
            .map_or(true, |code| code != 0)
    }
}

fn need(step: &Step, n: usize) -> Result<&str, StepError> {
    step.args
        .get(n)
        .map(String::as_str)
        .ok_or_else(|| StepError::Failed(format!("{} 의 인자가 부족합니다", step.cmd)))
}

fn write_text(path: &str, text: &str) -> Result<i32, StepError> {
    std::fs::write(path, text.as_bytes())
        .map(|()| 0)
        .map_err(|e| StepError::Failed(format!("{path} 을(를) 쓰지 못했습니다: {e}")))
}

/// `(write-state)`: the install state with `installed_at` = now (KST, to the second), UTF-8
/// without a BOM, indented by 2.
fn write_state(path: &str, json: &str) -> Result<i32, StepError> {
    let mut state: Value = serde_json::from_str(json)
        .map_err(|e| StepError::Failed(format!("설치 상태가 JSON이 아닙니다: {e}")))?;
    let Some(object) = state.as_object_mut() else {
        return Err(StepError::Failed("설치 상태가 JSON 객체가 아닙니다".into()));
    };
    object.insert("installed_at".into(), Value::from(kst_now()));
    let text = serde_json::to_string_pretty(&state).expect("a JSON value always serializes");
    write_text(path, &text)
}

/// `(write-json)`: the text as given; a `"recorded_at": null` is stamped with now (F15).
fn write_json(path: &str, json: &str) -> Result<i32, StepError> {
    match serde_json::from_str::<Value>(json) {
        Ok(Value::Object(mut o)) if o.get("recorded_at") == Some(&Value::Null) => {
            o.insert("recorded_at".into(), Value::from(kst_now()));
            write_text(path, &Value::Object(o).to_string())
        }
        _ => write_text(path, json),
    }
}

/// `(wait)`: `GET <url>` every second until it answers 200 or `seconds` pass. Only
/// `http://127.0.0.1:<port>/…` (Y31), never through a proxy, 2 s per try.
fn wait_ready(url: &str, seconds: &str) -> Result<i32, StepError> {
    let local = url
        .strip_prefix("http://127.0.0.1:")
        .and_then(|rest| rest.split_once('/'))
        .is_some_and(|(port, _)| !port.is_empty() && port.bytes().all(|b| b.is_ascii_digit()));
    if !local {
        return Err(StepError::Failed(format!(
            "{url} 은(는) 이 PC(127.0.0.1)의 주소가 아닙니다"
        )));
    }
    let seconds: u64 = seconds
        .parse()
        .map_err(|_| StepError::Failed(format!("대기 시간 {seconds} 이(가) 숫자가 아닙니다")))?;
    let config = ureq::Agent::config_builder()
        .proxy(None)
        .timeout_global(Some(Duration::from_secs(2)))
        .http_status_as_error(false)
        .build();
    let agent = ureq::Agent::new_with_config(config);
    let deadline = Instant::now() + Duration::from_secs(seconds);
    loop {
        if agent.get(url).call().is_ok_and(|r| r.status() == 200) {
            return Ok(0);
        }
        if Instant::now() >= deadline {
            return Err(StepError::Failed(format!(
                "{url} 이(가) {seconds}초 안에 응답하지 않았습니다"
            )));
        }
        std::thread::sleep(Duration::from_secs(1));
    }
}

impl<R: Runner, W: Write> Executor for RealExecutor<'_, R, W> {
    fn condition(&mut self, when: &str) -> bool {
        match when {
            "service_exists" => self.host.service_exists(),
            "no_backup_yet" => !self.data_file_exists("auditpol-backup.csv"),
            // install-state.json (or an earlier --enable) already holds the values from before
            // our first change.
            "no_registry_record_yet" => {
                !self.data_file_exists("audit-policy-state.json")
                    && !self.data_file_exists("install-state.json")
            }
            "old_exists" => self
                .install_dir
                .as_ref()
                .is_some_and(|i| Path::new(&format!("{}.old", i.display())).exists()),
            "firewall_rule_missing" => self.firewall_rule_missing(),
            // A condition this executor does not know never runs its step.
            _ => false,
        }
    }

    fn internal(&mut self, step: &Step) -> Result<i32, StepError> {
        match step.cmd.as_str() {
            "(admin)" => {
                if self.host.is_admin() {
                    Ok(0)
                } else {
                    Err(StepError::NotAdmin)
                }
            }
            "(check-os)" => self.check_os(need(step, 0)?),
            "(stage)" => self.stage_payload(need(step, 0)?, need(step, 1)?),
            "(stop-apps)" => stop_apps(Path::new(need(step, 0)?))
                .map(|()| 0)
                .map_err(StepError::Failed),
            "(swap)" => swap(
                Path::new(need(step, 0)?),
                Path::new(need(step, 1)?),
                Path::new(need(step, 2)?),
                &StdFs,
                &self.owners(),
            )
            .map(|()| 0)
            .map_err(StepError::Failed),
            "(registry-set)" => self.registry_set(step),
            "(shortcut)" => create_shortcut(
                Path::new(need(step, 0)?),
                Path::new(need(step, 1)?),
                need(step, 2)?,
                need(step, 3)?,
            )
            .map(|()| 0)
            .map_err(StepError::Failed),
            "(remove-old)" => remove_old(Path::new(need(step, 0)?))
                .map(|()| 0)
                .map_err(StepError::Failed),
            "(secure-data-root)" => {
                let owners = self.owners();
                initialize_data_root(
                    Path::new(need(step, 0)?),
                    &self.data_root_owner,
                    &self.data_root_sids,
                    &owners,
                    &self.script,
                )
                .map(|()| 0)
                .map_err(StepError::Failed)
            }
            "(write-state)" => write_state(need(step, 0)?, need(step, 1)?),
            "(write-json)" => write_json(need(step, 0)?, need(step, 1)?),
            "(reg-restore)" => {
                let (runner, out) = (&mut self.runner, &mut self.out);
                restore_registry(
                    &step.args,
                    &mut |cmd, args| {
                        runner
                            .run(cmd, args, false)
                            .map_err(|e| spawn_error(cmd, e))
                    },
                    &mut |line| {
                        let _ = writeln!(out, "{line}");
                    },
                )
            }
            "(wait)" => wait_ready(need(step, 0)?, need(step, 1)?),
            _ => Err(StepError::Failed("아직 구현되지 않았습니다".into())),
        }
    }

    fn native(&mut self, cmd: &str, args: &[String]) -> Result<i32, StepError> {
        self.runner
            .run(cmd, args, false)
            .map_err(|e| spawn_error(cmd, e))
    }

    fn after(&mut self, id: &str) -> Result<(), StepError> {
        if id != "stop_existing" {
            return Ok(());
        }
        let started = Instant::now();
        loop {
            if self.host.service_stopped() {
                return Ok(());
            }
            if started.elapsed() >= self.stop_wait {
                return Err(StepError::Failed(format!(
                    "서비스 {SERVICE_NAME} 이(가) {}초 안에 멈추지 않았습니다",
                    self.stop_wait.as_secs()
                )));
            }
            std::thread::sleep(Duration::from_secs(1));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::host::FakeHost;
    use crate::install::plan::{Plan, Step};
    use crate::install::registry::{FakeRegistry, RegValue};
    use crate::install::shortcut::read_shortcut;
    use crate::install::testutil::*;
    use serde_json::{Value, json};
    use std::fs;
    use std::io::{Read, Write};

    /// Records every tool call; answers with a fixed exit code per tool. Never runs anything.
    #[derive(Default)]
    struct FakeRunner {
        calls: Vec<(String, Vec<String>, bool)>,
        codes: std::collections::HashMap<String, i32>,
        fail: bool,
    }
    impl Runner for FakeRunner {
        fn run(&mut self, cmd: &str, args: &[String], quiet: bool) -> std::io::Result<i32> {
            self.calls.push((cmd.into(), args.to_vec(), quiet));
            if self.fail {
                return Err(std::io::Error::other("없음"));
            }
            Ok(*self.codes.get(cmd).unwrap_or(&0))
        }
    }

    fn plan(
        script: &str,
        install_dir: Option<&Path>,
        data_root: Option<&Path>,
        steps: Vec<Step>,
    ) -> Plan {
        Plan {
            script: script.into(),
            version: None,
            layout: None,
            install_dir: install_dir.map(|p| p.display().to_string()),
            data_root: data_root.map(|p| p.display().to_string()),
            service_mode: None,
            steps,
            notes: vec![],
        }
    }
    fn st(id: &str, cmd: &str, args: &[&str]) -> Step {
        Step {
            id: id.into(),
            cmd: cmd.into(),
            args: args.iter().map(|a| a.to_string()).collect(),
            ok: vec![0],
            when: None,
        }
    }

    #[test]
    fn conditions_look_at_the_folders_the_host_and_the_firewall() {
        let s = Scratch::new();
        let (inst, data) = (s.path().join("i"), s.path().join("d"));
        let fw = st(
            "firewall",
            "netsh",
            &[
                "advfirewall",
                "firewall",
                "add",
                "rule",
                "name=MCP Monitor (9701)",
                "dir=in",
            ],
        );
        let p = plan("install", Some(&inst), Some(&data), vec![fw]);
        let mut h = FakeHost::new();
        let mut ex = RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new());
        assert!(!ex.condition("service_exists"));
        assert!(
            ex.condition("no_backup_yet")
                && ex.condition("no_registry_record_yet")
                && !ex.condition("old_exists")
        );
        assert!(
            !ex.condition("no_such_condition"),
            "an unknown condition never runs its step"
        );
        fs::create_dir_all(data.join("data")).unwrap();
        fs::write(data.join("data/auditpol-backup.csv"), "x").unwrap();
        fs::write(data.join("data/install-state.json"), "{}").unwrap();
        fs::create_dir_all(s.path().join("i.old")).unwrap();
        assert!(
            !ex.condition("no_backup_yet")
                && !ex.condition("no_registry_record_yet")
                && ex.condition("old_exists")
        );
        fs::remove_file(data.join("data/install-state.json")).unwrap();
        fs::write(data.join("data/audit-policy-state.json"), "{}").unwrap();
        assert!(!ex.condition("no_registry_record_yet"));
        // firewall_rule_missing asks netsh quietly for the rule this plan adds: 0 = it exists.
        assert!(!ex.condition("firewall_rule_missing"));
        ex.runner.codes.insert("netsh".into(), 1);
        assert!(ex.condition("firewall_rule_missing"));
        let show = (
            String::from("netsh"),
            [
                "advfirewall",
                "firewall",
                "show",
                "rule",
                "name=MCP Monitor (9701)",
            ]
            .map(String::from)
            .to_vec(),
            true,
        );
        assert_eq!(ex.runner.calls, [show.clone(), show]);
        drop(ex);
        h.service = true;
        let mut ex = RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new());
        assert!(ex.condition("service_exists"));
    }

    #[test]
    fn admin_step_needs_an_administrator() {
        let p = plan("install", None, None, vec![]);
        let mut h = FakeHost::new();
        let step = st("require_admin", "(admin)", &[]);
        assert_eq!(
            RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new()).internal(&step),
            Err(StepError::NotAdmin)
        );
        h.admin = true;
        assert_eq!(
            RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new()).internal(&step),
            Ok(0)
        );
    }

    #[test]
    fn native_steps_go_through_the_runner_with_their_arguments() {
        let p = plan("install", None, None, vec![]);
        let h = FakeHost::new();
        let mut runner = FakeRunner::default();
        runner.codes.insert("sc.exe".into(), 1062);
        let mut ex = RealExecutor::new(&p, &h, runner, Vec::new());
        let args = ["stop".to_string(), "mcp-monitor".into()];
        assert_eq!(ex.native("sc.exe", &args), Ok(1062));
        assert_eq!(
            ex.runner.calls,
            [("sc.exe".to_string(), args.to_vec(), false)]
        );
        ex.runner.fail = true;
        assert!(
            matches!(ex.native("auditpol", &[]), Err(StepError::Failed(m)) if m.contains("auditpol"))
        );
    }

    #[test]
    fn the_system_runner_returns_system32_exit_codes() {
        // Ruling F17 (Plan 5 T151): exit codes come back from System32 tools.
        assert_eq!(
            SystemRunner
                .run(
                    "cmd.exe",
                    &["/d".into(), "/c".into(), "exit".into(), "7".into()],
                    true
                )
                .unwrap(),
            7
        );
        assert_eq!(
            SystemRunner
                .run("cmd", &["/d".into(), "/c".into(), "exit 0".into()], true)
                .unwrap(),
            0
        );
        assert_eq!(
            tool_path("auditpol"),
            crate::winutil::system_tool("auditpol.exe")
        );
        assert_eq!(tool_path("sc.exe"), crate::winutil::system_tool("sc.exe"));
        assert_eq!(tool_path("SC.EXE"), crate::winutil::system_tool("SC.EXE"));
    }

    #[test]
    fn write_state_stamps_kst_and_writes_utf8_without_bom() {
        let s = Scratch::new();
        let p = plan("install", None, None, vec![]);
        let h = FakeHost::new();
        let mut ex = RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new());
        let target = s.path().join("install-state.json");
        let state = json!({"installed_at": null, "version": "1.1.0", "registry_before": {"a": null, "b": 0}, "installer": "desktop"});
        let step = st(
            "install_state",
            "(write-state)",
            &[&target.display().to_string(), &state.to_string()],
        );
        assert_eq!(ex.internal(&step), Ok(0));
        let bytes = fs::read(&target).unwrap();
        assert!(!bytes.starts_with(b"\xef\xbb\xbf"));
        let text = String::from_utf8(bytes).unwrap();
        assert!(
            text.contains("\n  \"version\": \"1.1.0\""),
            "indent 2: {text}"
        );
        let mut written: Value = serde_json::from_str(&text).unwrap();
        let at = written["installed_at"].as_str().unwrap().to_string();
        assert!(
            regex::Regex::new(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+09:00$")
                .unwrap()
                .is_match(&at),
            "{at}"
        );
        written["installed_at"] = Value::Null;
        assert_eq!(written, state);
        let bad = st(
            "install_state",
            "(write-state)",
            &[&target.display().to_string(), "[1]"],
        );
        assert!(matches!(ex.internal(&bad), Err(StepError::Failed(_))));
        assert!(matches!(
            ex.internal(&st("install_state", "(write-state)", &[])),
            Err(StepError::Failed(_))
        ));
    }

    #[test]
    fn write_json_writes_as_given_and_stamps_recorded_at() {
        let s = Scratch::new();
        let p = plan("audit-policy", None, None, vec![]);
        let h = FakeHost::new();
        let mut ex = RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new());
        let info = s.path().join("install.json");
        let text = r#"{"version":"1.1.0","local_port":8700}"#;
        assert_eq!(
            ex.internal(&st(
                "install_info",
                "(write-json)",
                &[&info.display().to_string(), text]
            )),
            Ok(0)
        );
        assert_eq!(fs::read_to_string(&info).unwrap(), text);
        let rec = s.path().join("audit-policy-state.json");
        let record =
            json!({"registry_before": {"x": null}, "audit_backup": "b.csv", "recorded_at": null})
                .to_string();
        assert_eq!(
            ex.internal(&st(
                "record_registry",
                "(write-json)",
                &[&rec.display().to_string(), &record]
            )),
            Ok(0)
        );
        let v: Value = serde_json::from_str(&fs::read_to_string(&rec).unwrap()).unwrap();
        assert!(
            v["recorded_at"].as_str().unwrap().ends_with("+09:00"),
            "F15: {v}"
        );
        assert_eq!(
            (v["registry_before"].clone(), v["audit_backup"].clone()),
            (json!({"x": null}), json!("b.csv"))
        );
    }

    #[test]
    fn secure_data_root_initializes_the_data_root_for_this_script() {
        let s = Scratch::new();
        let root = s.path().join("MCP Monitor");
        let p = plan("audit-policy", None, Some(&root), vec![]);
        let h = FakeHost::new();
        let mut ex = RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new());
        // Without admin rights this account stands in for Administrators (Y18).
        ex.data_root_owner = me();
        ex.data_root_sids = owners();
        assert_eq!(
            ex.internal(&st(
                "secure_data_root",
                "(secure-data-root)",
                &[&root.display().to_string()]
            )),
            Ok(0)
        );
        let marker: Value = serde_json::from_str(
            &fs::read_to_string(root.join("data/mcp-monitor-data-root.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(marker["created_by"], "audit-policy");
        fs::write(s.path().join("file"), "x").unwrap();
        let r = ex.internal(&st(
            "secure_data_root",
            "(secure-data-root)",
            &[&s.path().join("file").display().to_string()],
        ));
        assert!(matches!(r, Err(StepError::Failed(m)) if m.contains("폴더가 아닙니다")));
        assert_eq!(
            ADMINISTRATORS,
            RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new()).data_root_owner
        );
    }

    #[test]
    fn reg_restore_prints_its_line_and_unknown_internals_are_not_ready() {
        let p = plan("audit-policy", None, None, vec![]);
        let h = FakeHost::new();
        let mut ex = RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new());
        assert_eq!(
            ex.internal(&st("restore_registry", "(reg-restore)", &[])),
            Ok(0)
        );
        assert_eq!(
            String::from_utf8(ex.out.clone()).unwrap(),
            "  되돌릴 레지스트리 값이 없습니다(install-state.json 없음).\n"
        );
        assert!(ex.runner.calls.is_empty());
        let entry = format!("{}=null", crate::install::audit::AUDIT_VALUE);
        assert_eq!(
            ex.internal(&st("restore_registry", "(reg-restore)", &[&entry])),
            Ok(0)
        );
        assert_eq!(ex.runner.calls[0].0, "reg");
        assert_eq!(
            ex.internal(&st("x", "(nope)", &[])),
            Err(StepError::Failed("아직 구현되지 않았습니다".into()))
        );
        // Task 7's actions exist now: without their arguments they fail on those, not as missing.
        for cmd in [
            "(check-os)",
            "(stage)",
            "(stop-apps)",
            "(swap)",
            "(registry-set)",
            "(shortcut)",
            "(remove-old)",
        ] {
            assert_eq!(
                ex.internal(&st("x", cmd, &[])),
                Err(StepError::Failed(format!("{cmd} 의 인자가 부족합니다"))),
                "{cmd}"
            );
        }
    }

    #[test]
    fn check_os_warnings_cover_home_program_files_and_webview2() {
        let pf = Path::new(r"C:\Program Files");
        let w = check_os_warnings(
            "Microsoft Windows 11 Home",
            101,
            Path::new(r"D:\apps\MCP Monitor"),
            pf,
            None,
        );
        assert_eq!(w.len(), 3);
        assert!(
            w[0].contains("RDP") && w[1].contains("Program Files") && w[2].contains("WebView2"),
            "{w:?}"
        );
        assert!(
            check_os_warnings(
                "Microsoft Windows 11 Pro",
                48,
                &pf.join("MCP Monitor"),
                pf,
                Some("156.0.0.0")
            )
            .is_empty()
        );
        assert!(
            check_os_warnings(
                "Microsoft Windows 11 Pro",
                48,
                &pf.join("MCP Monitor"),
                pf,
                Some("0.0.0.0")
            )[0]
            .contains("WebView2")
        );
        // A Home SKU whatever the caption says; Program Files compared ignoring case (F04).
        let w = check_os_warnings(
            "Microsoft Windows 11",
            98,
            Path::new(r"c:\program files\MCP Monitor"),
            pf,
            Some("156.0.0.0"),
        );
        assert_eq!(w.len(), 1, "{w:?}");
        assert_eq!(
            w[0],
            "경고: Microsoft Windows 11은(는) RDP 호스트가 아니어서 세션 수집이 동작하지 않습니다. 설치는 계속합니다."
        );
        assert_eq!(
            check_os_warnings("Microsoft Windows 11 Pro", 48, pf, pf, Some("1.0"))[0],
            r"경고: C:\Program Files 은(는) Program Files 밖입니다. 서비스(SYSTEM)가 이 폴더의 프로그램을 실행하므로 일반 사용자가 쓸 수 없는 폴더여야 합니다.",
            "Program Files itself is not a folder inside it"
        );
    }

    #[test]
    fn check_os_step_prints_the_warnings_and_goes_on() {
        let p = plan("install", None, None, vec![]);
        let mut h = FakeHost::new();
        let inst = format!(r"{}\MCP Monitor", h.env.get("ProgramFiles").unwrap());
        let step = st("check_os", "(check-os)", &[&inst]);
        let mut ex = RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new());
        assert_eq!(ex.internal(&step), Ok(0));
        assert!(ex.out.is_empty(), "{}", String::from_utf8_lossy(&ex.out));
        drop(ex);
        h.os = ("Microsoft Windows 11 Home".into(), 101);
        h.webview2 = None;
        let mut ex = RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new());
        assert_eq!(ex.internal(&step), Ok(0));
        let out = String::from_utf8(ex.out).unwrap();
        assert_eq!(out.lines().count(), 2, "{out}");
        assert!(out.contains("Microsoft Windows 11 Home은(는) RDP") && out.contains("WebView2"));
    }

    #[test]
    fn registry_values_are_typed_and_applied() {
        assert_eq!(
            parse_reg_value("DisplayName=REG_SZ:MCP Monitor").unwrap(),
            ("DisplayName".into(), RegValue::Sz("MCP Monitor".into()))
        );
        assert_eq!(
            parse_reg_value(r#"DisplayIcon=REG_SZ:"C:\a b\x.exe",0"#)
                .unwrap()
                .1,
            RegValue::Sz(r#""C:\a b\x.exe",0"#.into())
        );
        assert_eq!(
            parse_reg_value("NoModify=REG_DWORD:1").unwrap(),
            ("NoModify".into(), RegValue::Dword(1))
        );
        assert_eq!(
            parse_reg_value("X=REG_SZ:a=b").unwrap().1,
            RegValue::Sz("a=b".into())
        );
        for bad in [
            "X=REG_BINARY:1",
            "X=REG_DWORD:-1",
            "=REG_SZ:a",
            "X",
            "X=REG_DWORD:4294967296",
            "X=REG_DWORD:",
            "X=REG_DWORD:１",
            "X=REG_DWORD:0x1",
            "X=REG_DWORD:+1",
            "X=REG_DWORD: 1",
        ] {
            assert!(parse_reg_value(bad).is_err(), "{bad}");
        }
        let mut r = FakeRegistry::default();
        r.set_values("HKLM\\X", &[("A".into(), RegValue::Dword(1))])
            .unwrap();
        assert_eq!(r.string("HKLM\\X", "A"), None);
        r.delete_key("HKLM\\X").unwrap();
        assert!(r.subkeys("HKLM").is_empty());
    }

    #[test]
    fn registry_set_step_writes_the_uninstall_entry_and_checks_every_value_first() {
        let p = plan("install", None, None, vec![]);
        let h = FakeHost::new();
        let mut fake = FakeRegistry::default();
        let key = crate::install::host::UNINSTALL_KEY;
        {
            let mut ex = RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new());
            ex.registry = Box::new(&mut fake);
            let bad = st(
                "uninstall_entry",
                "(registry-set)",
                &[
                    key,
                    "DisplayName=REG_SZ:MCP Monitor",
                    "NoModify=REG_DWORD:x",
                ],
            );
            assert!(
                matches!(ex.internal(&bad), Err(StepError::Failed(m)) if m.contains("NoModify"))
            );
            let good = st(
                "uninstall_entry",
                "(registry-set)",
                &[
                    key,
                    "DisplayName=REG_SZ:MCP Monitor",
                    "DisplayVersion=REG_SZ:1.1.0",
                    "NoModify=REG_DWORD:1",
                ],
            );
            assert_eq!(ex.internal(&good), Ok(0));
        }
        assert_eq!(
            fake.0.len(),
            1,
            "nothing written by the refused step: {fake:?}"
        );
        assert_eq!(fake.string(key, "DisplayVersion").as_deref(), Some("1.1.0"));
        assert_eq!(fake.0[key]["NoModify"], RegValue::Dword(1));
        assert_eq!(
            fake.subkeys(r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            ["MCPMonitor"]
        );
    }

    #[test]
    fn shortcut_points_at_the_target() {
        let s = Scratch::new();
        let target = s.path().join("i").join("mcp-monitor.exe");
        std::fs::create_dir_all(target.parent().unwrap()).unwrap();
        std::fs::write(&target, b"MZ").unwrap();
        let lnk = s.path().join("MCP Monitor.lnk");
        create_shortcut(&lnk, &target, "", "MCP Monitor").unwrap();
        assert_eq!(
            read_shortcut(&lnk).unwrap(),
            (target.clone(), "MCP Monitor".to_string())
        );
        // The step replaces an existing shortcut.
        let p = plan("install", None, None, vec![]);
        let h = FakeHost::new();
        let mut ex = RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new());
        let step = st(
            "start_menu_shortcut",
            "(shortcut)",
            &[
                &lnk.display().to_string(),
                &target.display().to_string(),
                "",
                "MCP Monitor 1.1.0",
            ],
        );
        assert_eq!(ex.internal(&step), Ok(0));
        assert_eq!(read_shortcut(&lnk).unwrap().1, "MCP Monitor 1.1.0");
        assert!(read_shortcut(&s.path().join("missing.lnk")).is_err());
    }

    /// A release payload of three files, packed from a scratch folder.
    fn release_payload(s: &Scratch, version: &str) -> PayloadSource {
        let src = s.path().join(format!("payload-{version}"));
        fs::create_dir_all(src.join("bin/monitor")).unwrap();
        fs::write(
            src.join("bundle.json"),
            format!(r#"{{"layout":"pyinstaller","version":"{version}","agent":"desktop"}}"#),
        )
        .unwrap();
        fs::write(src.join("bin/monitor/mcp-monitor-server.exe"), b"MZ server").unwrap();
        let p = crate::payload_pack::pack_dir(&src, 3).unwrap();
        PayloadSource {
            archive: p.archive,
            sha256: p.sha256,
            manifest: p.manifest,
            kind: "release".into(),
        }
    }

    #[test]
    fn stage_swap_and_remove_old_steps_upgrade_an_install_folder() {
        let s = Scratch::new();
        let inst = s.path().join("MCP Monitor");
        let (i, staging, old) = (
            inst.display().to_string(),
            format!("{}.staging", inst.display()),
            format!("{}.old", inst.display()),
        );
        fs::create_dir_all(&inst).unwrap();
        fs::write(inst.join("bundle.json"), r#"{"version":"1.0.0"}"#).unwrap();
        let exe = s.path().join("downloads").join("mcp-monitor-1.1.0.exe");
        fs::create_dir_all(exe.parent().unwrap()).unwrap();
        fs::write(&exe, b"MZ 1.1.0").unwrap();
        let p = plan("install", Some(&inst), None, vec![]);
        let h = FakeHost::new();
        let mut ex = RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new());
        ex.self_exe = Some(exe);
        ex.payload = Some(release_payload(&s, "1.1.0"));
        assert_eq!(
            ex.internal(&st("stage_payload", "(stage)", &[&staging, &i])),
            Ok(0)
        );
        assert!(String::from_utf8_lossy(&ex.out).contains("MB를 풀었습니다"));
        assert!(!ex.condition("old_exists"));
        assert_eq!(
            ex.internal(&st("stop_apps", "(stop-apps)", &[&i])),
            Ok(0),
            "nothing runs from the scratch install folder"
        );
        assert_eq!(
            ex.internal(&st("swap_install_dir", "(swap)", &[&staging, &i, &old])),
            Ok(0)
        );
        assert_eq!(fs::read(inst.join("mcp-monitor.exe")).unwrap(), b"MZ 1.1.0");
        assert!(
            fs::read_to_string(inst.join("bundle.json"))
                .unwrap()
                .contains("1.1.0")
        );
        assert!(ex.condition("old_exists"));
        assert_eq!(
            ex.internal(&st("cleanup_old", "(remove-old)", &[&old])),
            Ok(0)
        );
        assert!(!Path::new(&old).exists() && !Path::new(&staging).exists());
    }

    #[test]
    fn stage_step_refuses_the_installed_copy_and_the_fixture_payload() {
        let s = Scratch::new();
        let inst = s.path().join("MCP Monitor");
        let (i, staging) = (
            inst.display().to_string(),
            format!("{}.staging", inst.display()),
        );
        let p = plan("install", Some(&inst), None, vec![]);
        let h = FakeHost::new();
        let step = st("stage_payload", "(stage)", &[&staging, &i]);
        // Ruling F06: run from the install folder (a repair from the installed copy).
        let mut ex = RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new());
        ex.self_exe = Some(inst.join("mcp-monitor.exe"));
        ex.payload = Some(release_payload(&s, "1.1.0"));
        assert!(
            matches!(ex.internal(&step), Err(StepError::Failed(m)) if m.contains("다운로드한 mcp-monitor-1.1.0.exe로 실행하세요"))
        );
        // A test build embeds the fixture payload: never installed for real.
        let mut ex = RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new());
        assert_eq!(crate::payload::KIND, "fixture");
        assert!(
            matches!(ex.internal(&step), Err(StepError::Failed(m)) if m.contains("개발용(fixture)"))
        );
        assert!(!Path::new(&staging).exists());
    }

    /// A one-shot HTTP server on 127.0.0.1 that answers every request with `status`.
    fn http_server(status: u16) -> u16 {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        std::thread::spawn(move || {
            for stream in listener.incoming() {
                let Ok(mut stream) = stream else { break };
                let mut buf = [0u8; 2048];
                let _ = stream.read(&mut buf);
                let _ = write!(
                    stream,
                    "HTTP/1.1 {status} X\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                );
            }
        });
        port
    }

    #[test]
    fn wait_succeeds_on_200_and_gives_up_after_its_seconds() {
        let p = plan("install", None, None, vec![]);
        let h = FakeHost::new();
        let mut ex = RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new());
        let ok = format!("http://127.0.0.1:{}/api/channel", http_server(200));
        assert_eq!(ex.internal(&st("wait_ready", "(wait)", &[&ok, "5"])), Ok(0));
        let missing = format!("http://127.0.0.1:{}/api/channel", http_server(404));
        let started = std::time::Instant::now();
        let r = ex.internal(&st("wait_ready", "(wait)", &[&missing, "1"]));
        assert_eq!(
            r,
            Err(StepError::Failed(format!(
                "{missing} 이(가) 1초 안에 응답하지 않았습니다"
            )))
        );
        assert!(started.elapsed() < std::time::Duration::from_secs(5));
        // Only this PC: never a proxy, never another host.
        for url in [
            "http://example.com/api/channel",
            "https://127.0.0.1:1/",
            "http://127.0.0.1.evil/x",
        ] {
            assert!(
                matches!(
                    ex.internal(&st("wait_ready", "(wait)", &[url, "1"])),
                    Err(StepError::Failed(_))
                ),
                "{url}"
            );
        }
        assert!(matches!(
            ex.internal(&st("wait_ready", "(wait)", &[&ok, "x"])),
            Err(StepError::Failed(_))
        ));
    }

    #[test]
    fn after_stop_existing_waits_for_the_service_to_stop() {
        let p = plan("install", None, None, vec![]);
        let mut h = FakeHost::new();
        assert_eq!(
            RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new()).after("stop_existing"),
            Ok(())
        );
        h.running = true;
        let mut ex = RealExecutor::new(&p, &h, FakeRunner::default(), Vec::new());
        assert_eq!(ex.stop_wait, std::time::Duration::from_secs(60));
        ex.stop_wait = std::time::Duration::ZERO;
        assert_eq!(
            ex.after("stop_existing"),
            Err(StepError::Failed(
                "서비스 mcp-monitor 이(가) 0초 안에 멈추지 않았습니다".into()
            ))
        );
        assert_eq!(ex.after("service_start"), Ok(()));
    }
}
