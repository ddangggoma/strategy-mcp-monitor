//! `RealExecutor`: runs a plan on this PC (Plan 5's `$Internal`, `$Conditions`, `$AfterStep` and
//! `Invoke-Native`). System32 tools go through a [`Runner`] so tests never start one for real;
//! administrator rights and the service come from the [`Host`]. Task 7 and 8 add the internal
//! actions that are still `아직 구현되지 않았습니다`.

use crate::install::acl::{ADMINISTRATORS, SYSTEM, initialize_data_root, kst_now};
use crate::install::audit::restore_registry;
use crate::install::host::{Host, SERVICE_NAME};
use crate::install::plan::{Executor, Plan, Step, StepError};
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
        }
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
            "(secure-data-root)" => {
                let owners = [
                    SYSTEM.to_string(),
                    ADMINISTRATORS.to_string(),
                    self.host.user_sid(),
                ];
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
        for cmd in ["(stage)", "(swap)", "(registry-set)", "(nope)"] {
            assert_eq!(
                ex.internal(&st("x", cmd, &[])),
                Err(StepError::Failed("아직 구현되지 않았습니다".into())),
                "{cmd}"
            );
        }
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
