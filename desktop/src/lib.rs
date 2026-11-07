//! MCP Monitor desktop executable: one GUI-subsystem exe whose first argument picks the mode.

use std::ffi::OsString;
use std::path::{Path, PathBuf};

pub mod agent;
pub mod app;
pub mod cli;
pub mod install;
pub mod payload;
pub mod payload_pack;
pub mod version;
pub mod winutil;

use cli::{ArgError, Command};
use install::exec::{RealExecutor, SystemRunner};
use install::host::{Host, SystemHost};
use install::plan::{Plan, print_dry_run, run_plan};
use std::io::Write;

/// What [`run_with`] needs from Windows to re-run itself elevated. The real one is
/// [`SystemElevator`]; tests use a fake, so no test ever shows a UAC prompt or a message box.
pub trait Elevator {
    fn is_elevated(&self) -> bool;
    /// True in the copy that a relaunch started (see [`winutil::parent_is_same_exe`]).
    fn parent_is_same_exe(&self) -> bool;
    fn current_exe(&self) -> std::io::Result<PathBuf>;
    fn elevate_and_wait(&self, exe: &Path, args: &[String]) -> Result<i32, String>;
    fn error_box(&self, text: &str);
    /// The end of an `--interactive` install, uninstall or audit-policy run (the elevated copy has
    /// no console to print to).
    fn info_box(&self, text: &str);
}

/// Everything [`run_with`] needs from Windows: elevation and message boxes ([`Elevator`]) and the
/// window modes' PC access ([`app::Desktop`]).
pub trait System: Elevator + app::Desktop {}

impl<T: Elevator + app::Desktop> System for T {}

pub struct SystemElevator;

impl Elevator for SystemElevator {
    fn is_elevated(&self) -> bool {
        winutil::is_elevated()
    }
    fn parent_is_same_exe(&self) -> bool {
        winutil::parent_is_same_exe()
    }
    fn current_exe(&self) -> std::io::Result<PathBuf> {
        std::env::current_exe()
    }
    fn elevate_and_wait(&self, exe: &Path, args: &[String]) -> Result<i32, String> {
        winutil::elevate_and_wait(exe, args)
    }
    fn error_box(&self, text: &str) {
        winutil::message_box(text, winutil::MsgKind::Error);
    }
    fn info_box(&self, text: &str) {
        winutil::message_box(text, winutil::MsgKind::Info);
    }
}

/// Entry point for `mcp-monitor.exe` (arguments after the program name); returns the exit code.
pub fn run(args: Vec<OsString>) -> i32 {
    run_with(args, &SystemElevator)
}

/// The arguments as Unicode strings; one that is not valid UTF-16 is an argument error.
fn decode_args(args: Vec<OsString>) -> Result<Vec<String>, ArgError> {
    args.into_iter()
        .enumerate()
        .map(|(i, a)| {
            a.into_string()
                .map_err(|_| ArgError(format!("인자 {}이(가) 올바른 유니코드가 아닙니다", i + 1)))
        })
        .collect()
}

pub fn run_with(args: Vec<OsString>, sys: &dyn System) -> i32 {
    let cmd = match decode_args(args).and_then(|a| cli::parse(&a)) {
        Ok(cmd) => cmd,
        Err(e) => {
            err_line(format_args!("오류: {}", e.0));
            return 2;
        }
    };
    if cli::needs_relaunch(&cmd, sys.is_elevated()) && !sys.parent_is_same_exe() {
        return relaunch_elevated(&cmd, sys);
    }
    match cmd {
        Command::Version => {
            out_line(version::version_line(
                version::PRODUCT,
                payload::ARCHIVE_SHA256,
                payload::KIND,
                cfg!(feature = "dev"),
            ));
            0
        }
        Command::VerifyPayload(dir) => verify_payload(&dir),
        Command::Install(a) => {
            let host = SystemHost::new();
            let built = install::install_plan::build_install_plan(&a, &host);
            run_installer(built, a.dry_run, a.interactive, &host, sys, |plan, _| {
                install_done_line(plan)
            })
        }
        Command::Uninstall(a) => {
            let host = SystemHost::new();
            let built = install::uninstall_plan::build_uninstall_plan(&a, &host);
            run_installer(
                built,
                a.dry_run,
                a.interactive,
                &host,
                sys,
                |plan, reboot| uninstall_done_line(plan, a.remove_data, reboot),
            )
        }
        Command::AuditPolicy(a) => {
            let host = SystemHost::new();
            let built = install::audit::build_audit_plan(&a, &host);
            let done = if a.enable {
                "감사 정책을 켰습니다."
            } else {
                "감사 정책을 되돌렸습니다."
            };
            run_installer(built, a.dry_run, a.interactive, &host, sys, |_, _| {
                done.to_string()
            })
        }
        Command::Agent(a) => run_agent(&a),
        Command::Auto => app::run_auto(sys),
        Command::App(a) => app::run_app_command(sys, &a),
        Command::Autostart(on) => run_autostart(sys, on),
    }
}

/// `agent`: the token and the server key come out of the environment before anything else, so no
/// child (WebView2) inherits them, then every `WEBVIEW2_*` variable (not in `dev` builds, Y24). A
/// missing or bad secret is an argument error: `오류: …` + 2. The exit code is the runner's.
fn run_agent(args: &cli::AgentArgs) -> i32 {
    let mut env = agent::config::ProcessEnv;
    let (token, key) = agent::config::take_secrets(&mut env);
    if !cfg!(feature = "dev") {
        agent::config::strip_webview2_env(&mut env);
    }
    let cfg = match agent::config::config_from(args, token, key) {
        Ok(cfg) => cfg,
        Err(e) => {
            err_line(format_args!("오류: {}", e.0));
            return 2;
        }
    };
    match cfg.dialog {
        cli::Dialog::Print => agent::run_print(&cfg),
        cli::Dialog::Webview => agent::webview::run_webview_agent(cfg),
    }
}

/// `autostart on|off`: the current user's `Run` value for the installed copy (the Apps & features
/// location). Not installed: `오류: …` + 1; a registry failure: `[실패] autostart: …` + 1.
fn run_autostart(sys: &dyn System, on: bool) -> i32 {
    let Some(installed) = sys.installed() else {
        err_line(
            "오류: MCP Monitor가 설치되어 있지 않습니다(앱 및 기능에 항목이 없습니다). 먼저 mcp-monitor.exe로 설치하세요.",
        );
        return 1;
    };
    match sys.set_autostart(&installed.install_location, on) {
        Ok(()) => {
            out_line(if on {
                "로그인할 때 MCP Monitor 트레이를 시작합니다."
            } else {
                "로그인할 때 MCP Monitor 트레이를 시작하지 않습니다."
            });
            0
        }
        Err(e) => {
            out_line(format_args!("[실패] autostart: {e}"));
            1
        }
    }
}

/// Re-runs this same exe elevated with arguments rebuilt from the parsed command (absolute paths,
/// no `--dry-run`, `--interactive` last) and returns its exit code; errors go to a message box + 1.
fn relaunch_elevated(cmd: &Command, elevator: &dyn Elevator) -> i32 {
    let cmd = match cli::with_absolute_paths(cmd, |p| std::path::absolute(p)) {
        Ok(cmd) => cmd,
        Err(e) => {
            err_line(format_args!("오류: {}", e.0));
            return 2;
        }
    };
    let result = elevator
        .current_exe()
        .map_err(|e| format!("실행 파일 위치를 알 수 없습니다: {e}"))
        .and_then(|exe| elevator.elevate_and_wait(&exe, &cli::relaunch_args(&cmd)));
    match result {
        Ok(code) => code,
        Err(message) => {
            elevator.error_box(&message);
            1
        }
    }
}

/// The last line of a successful install.
fn install_done_line(plan: &Plan) -> String {
    let port = plan
        .steps
        .iter()
        .find(|s| s.id == "install_info")
        .and_then(|s| serde_json::from_str::<serde_json::Value>(s.args.get(1)?).ok())
        .and_then(|v| v["local_port"].as_u64())
        .unwrap_or(u64::from(install::install_plan::DEFAULT_LOCAL_PORT));
    format!("설치 완료: http://127.0.0.1:{port}/admin/setup 에서 첫 Admin 계정을 만드세요.")
}

/// The last line of a successful uninstall, plus a second line when this exe (run from the
/// install folder) is left for the next restart.
fn uninstall_done_line(plan: &Plan, remove_data: bool, reboot_pending: bool) -> String {
    let mut line = if remove_data {
        "제거 완료(데이터 포함).".to_string()
    } else {
        format!(
            "제거 완료. 데이터는 {} 에 남아 있습니다(지우려면 --remove-data).",
            plan.data_root.as_deref().unwrap_or_default()
        )
    };
    if reboot_pending {
        line.push_str("\n설치 폴더의 남은 파일은 다시 시작할 때 지워집니다.");
    }
    line
}

/// Standard output (`Stderr`: standard error) that never fails and never panics: when the reader
/// went away (a closed pipe), or there is no handle at all, the text is dropped and the command's
/// exit code stays what the command decided. `println!` would panic there instead. In unit tests
/// the text goes through `print!` / `eprint!`, so the test harness captures what a plan prints.
/// Every write is a whole `&str` piece of a `writeln!`.
struct Stdout;
struct Stderr;

impl Write for Stdout {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        if cfg!(test) {
            print!("{}", String::from_utf8_lossy(buf));
        } else {
            let _ = std::io::stdout().write_all(buf);
        }
        Ok(buf.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        let _ = std::io::stdout().flush();
        Ok(())
    }
}

impl Write for Stderr {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        if cfg!(test) {
            eprint!("{}", String::from_utf8_lossy(buf));
        } else {
            let _ = std::io::stderr().write_all(buf);
        }
        Ok(buf.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

/// One line to standard output, through [`Stdout`] (never panics).
fn out_line(line: impl std::fmt::Display) {
    let _ = writeln!(Stdout, "{line}");
    let _ = Stdout.flush();
}

/// One line to standard error, through [`Stderr`] (never panics).
fn err_line(line: impl std::fmt::Display) {
    let _ = writeln!(Stderr, "{line}");
}

/// Writes through to `inner` and keeps a copy, so an `--interactive` run can show its last
/// `[실패]` line in a message box.
struct Tee<W: Write> {
    inner: W,
    copy: Vec<u8>,
}

impl<W: Write> Write for Tee<W> {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        self.copy.extend_from_slice(buf);
        self.inner.write_all(buf)?;
        Ok(buf.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        self.inner.flush()
    }
}

/// What the error box of a failed `--interactive` run says: the last `[실패]` line, else the last
/// line (the administrator message).
fn failure_text(output: &[u8]) -> String {
    let text = String::from_utf8_lossy(output);
    let lines: Vec<&str> = text.lines().filter(|l| !l.trim().is_empty()).collect();
    match lines.iter().rposition(|l| l.starts_with("[실패]")) {
        // The failure and the `[복구]` lines run_plan printed after it.
        Some(i) => std::iter::once(lines[i])
            .chain(
                lines[i + 1..]
                    .iter()
                    .copied()
                    .filter(|l| l.starts_with("[복구]")),
            )
            .collect::<Vec<_>>()
            .join("\n"),
        None => lines
            .last()
            .map_or_else(|| "실패했습니다.".to_string(), |l| l.to_string()),
    }
}

/// `install` / `uninstall` / `audit-policy` after the plan is built: argument errors are
/// `오류: …` + 2, `--dry-run` prints the plan, otherwise the plan runs (0, or 1 at the first
/// failure) from System32 (a folder that is the current folder cannot be removed or moved). With
/// `--interactive` the result is also shown in a message box. `done` makes the last line from the
/// plan and whether files were left for the next restart.
fn run_installer(
    built: Result<Plan, ArgError>,
    dry_run: bool,
    interactive: bool,
    host: &dyn Host,
    elevator: &dyn Elevator,
    done: impl Fn(&Plan, bool) -> String,
) -> i32 {
    let plan = match built {
        Ok(plan) => plan,
        Err(e) => {
            err_line(format_args!("오류: {}", e.0));
            if interactive {
                elevator.error_box(&format!("오류: {}", e.0));
            }
            return 2;
        }
    };
    if dry_run {
        return print_dry_run(&plan, &mut Stdout, &mut Stderr);
    }
    // Unit tests share one process (and its current folder) with every other test.
    if !cfg!(test) {
        let _ = std::env::set_current_dir(winutil::system_dir());
    }
    let mut ex = RealExecutor::new(&plan, host, SystemRunner, Stdout);
    let mut out = Tee {
        inner: Stdout,
        copy: Vec::new(),
    };
    let code = run_plan(&plan, &mut ex, &mut out);
    if code == 0 {
        let line = done(&plan, ex.reboot_pending());
        out_line(&line);
        if interactive {
            elevator.info_box(&line);
        }
    } else if interactive {
        elevator.error_box(&failure_text(&out.copy));
    }
    code
}

/// `verify-payload <dir>`: checks the embedded archive and extracts it into `<dir>\payload`.
/// `<dir>` must be missing or an empty folder (Y34), so nothing of the caller's is overwritten.
fn verify_payload(dir: &Path) -> i32 {
    if dir.exists() {
        if !dir.is_dir() {
            err_line(format_args!(
                "오류: {}은(는) 폴더가 아닙니다",
                dir.display()
            ));
            return 2;
        }
        match std::fs::read_dir(dir) {
            Ok(mut entries) => {
                if entries.next().is_some() {
                    err_line(format_args!(
                        "오류: {}이(가) 비어 있지 않습니다",
                        dir.display()
                    ));
                    return 2;
                }
            }
            Err(e) => {
                err_line(format_args!(
                    "오류: {} 폴더를 읽을 수 없습니다: {e}",
                    dir.display()
                ));
                return 2;
            }
        }
    }
    let result =
        payload::verify_archive(payload::ARCHIVE, payload::ARCHIVE_SHA256).and_then(|()| {
            let m = payload::manifest();
            payload::extract(payload::ARCHIVE, &m, &dir.join("payload"))
                .map(|bytes| (m.files.len(), bytes))
        });
    match result {
        Ok((files, bytes)) => {
            out_line(format_args!("payload OK: {files} files, {bytes} bytes"));
            0
        }
        Err(e) => {
            out_line(format_args!("[실패] verify-payload: {e}"));
            1
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn release_builds_turn_off_tauri_dev_mode() {
        // Ruling F08: tauri's `custom-protocol` feature is on, so Tauri's own dev mode is off.
        assert!(!tauri::is_dev());
    }

    use crate::install::host::Installed;
    use std::cell::RefCell;
    use std::os::windows::ffi::OsStringExt;
    use std::path::{Path, PathBuf};

    /// Records what `run_with` asks for; never shows a UAC prompt, a message box or a window,
    /// never starts a process and never writes the registry.
    struct FakeElevator {
        elevated: bool,
        parent_is_same_exe: bool,
        answer: Result<i32, String>,
        exe: PathBuf,
        /// The Apps & features entry; after an elevated run that returned 0 it becomes `installs_to`.
        installed: RefCell<Option<Installed>>,
        installs_to: Option<Installed>,
        service: bool,
        bin_path: Option<String>,
        yes: bool,
        autostart_fails: bool,
        launched: RefCell<Vec<(PathBuf, Vec<String>)>>,
        boxes: RefCell<Vec<String>>,
        asked: RefCell<Vec<String>>,
        started: RefCell<Vec<PathBuf>>,
        windows: RefCell<Vec<(app::AppTarget, bool)>>,
        autostart: RefCell<Vec<(PathBuf, bool)>>,
    }

    impl FakeElevator {
        fn new(elevated: bool, answer: Result<i32, String>) -> FakeElevator {
            FakeElevator {
                elevated,
                parent_is_same_exe: false,
                answer,
                exe: PathBuf::from(r"C:\Users\u\Downloads\mcp-monitor-1.1.0.exe"),
                installed: RefCell::new(None),
                installs_to: None,
                service: false,
                bin_path: None,
                yes: false,
                autostart_fails: false,
                launched: RefCell::new(Vec::new()),
                boxes: RefCell::new(Vec::new()),
                asked: RefCell::new(Vec::new()),
                started: RefCell::new(Vec::new()),
                windows: RefCell::new(Vec::new()),
                autostart: RefCell::new(Vec::new()),
            }
        }
    }

    impl Elevator for FakeElevator {
        fn is_elevated(&self) -> bool {
            self.elevated
        }
        fn parent_is_same_exe(&self) -> bool {
            self.parent_is_same_exe
        }
        fn current_exe(&self) -> std::io::Result<PathBuf> {
            Ok(self.exe.clone())
        }
        fn elevate_and_wait(&self, exe: &Path, args: &[String]) -> Result<i32, String> {
            self.launched
                .borrow_mut()
                .push((exe.to_path_buf(), args.to_vec()));
            if self.answer == Ok(0) && self.installs_to.is_some() {
                *self.installed.borrow_mut() = self.installs_to.clone();
            }
            self.answer.clone()
        }
        fn error_box(&self, text: &str) {
            self.boxes.borrow_mut().push(text.to_string());
        }
        fn info_box(&self, text: &str) {
            self.boxes.borrow_mut().push(format!("info: {text}"));
        }
    }

    impl app::Desktop for FakeElevator {
        fn installed(&self) -> Option<Installed> {
            self.installed.borrow().clone()
        }
        fn service_exists(&self) -> bool {
            self.service
        }
        fn service_bin_path(&self) -> Option<String> {
            self.bin_path.clone()
        }
        fn env_folder(&self, name: &str) -> Option<PathBuf> {
            match name {
                "ProgramFiles" => Some(PathBuf::from(r"C:\Program Files")),
                "ProgramData" => Some(PathBuf::from(r"C:\ProgramData")),
                _ => None,
            }
        }
        fn ask_yes_no(&self, text: &str) -> bool {
            self.asked.borrow_mut().push(text.to_string());
            self.yes
        }
        fn start_app(&self, exe: &Path) -> Result<(), String> {
            self.started.borrow_mut().push(exe.to_path_buf());
            Ok(())
        }
        fn open_window(&self, target: app::AppTarget, background: bool) -> i32 {
            self.windows.borrow_mut().push((target, background));
            0
        }
        fn set_autostart(&self, install_dir: &Path, on: bool) -> Result<(), String> {
            if self.autostart_fails {
                return Err("접근이 거부되었습니다.".into());
            }
            self.autostart
                .borrow_mut()
                .push((install_dir.to_path_buf(), on));
            Ok(())
        }
    }

    fn args(v: &[&str]) -> Vec<OsString> {
        v.iter().map(OsString::from).collect()
    }

    #[test]
    fn version_flag_exits_0_and_bad_commands_exit_2() {
        let f = FakeElevator::new(false, Ok(0));
        assert_eq!(run_with(args(&["--version"]), &f), 0);
        assert_eq!(run_with(args(&["uninstall", "--bogus"]), &f), 2);
        assert_eq!(run_with(args(&["--version", "extra"]), &f), 2);
        assert_eq!(run_with(args(&["install", "--bogus"]), &f), 2);
        assert!(f.launched.borrow().is_empty() && f.boxes.borrow().is_empty());
    }

    #[test]
    fn arguments_that_are_not_valid_utf16_are_an_argument_error() {
        let lone_surrogate = OsString::from_wide(&[0x0061, 0xD800, 0x0062]);
        let f = FakeElevator::new(false, Ok(0));
        assert_eq!(
            run_with(
                vec![
                    "install".into(),
                    "--install-dir".into(),
                    lone_surrogate.clone()
                ],
                &f
            ),
            2
        );
        assert_eq!(run_with(vec![lone_surrogate], &f), 2);
        assert!(f.launched.borrow().is_empty());
        assert_eq!(
            decode_args(vec!["x".into(), OsString::from_wide(&[0xDC00])])
                .unwrap_err()
                .0,
            "인자 2이(가) 올바른 유니코드가 아닙니다"
        );
    }

    #[test]
    fn an_interactive_install_relaunches_the_same_exe_elevated_with_parsed_options() {
        let f = FakeElevator::new(false, Ok(7));
        let code = run_with(
            args(&[
                "install",
                "--open-firewall",
                "--interactive",
                "--install-dir",
                r"D:\MCP Monitor",
                "--local-port",
                "9700",
            ]),
            &f,
        );
        assert_eq!(code, 7, "the elevated child's exit code is ours");
        let launched = f.launched.borrow();
        assert_eq!(launched.len(), 1);
        assert_eq!(
            launched[0].0,
            PathBuf::from(r"C:\Users\u\Downloads\mcp-monitor-1.1.0.exe")
        );
        assert_eq!(
            launched[0].1,
            [
                "install",
                "--install-dir",
                r"D:\MCP Monitor",
                "--open-firewall",
                "--local-port",
                "9700",
                "--interactive"
            ]
        );
        assert!(f.boxes.borrow().is_empty());
    }

    #[test]
    fn the_relaunch_gets_absolute_paths() {
        let f = FakeElevator::new(false, Ok(0));
        run_with(
            args(&["audit-policy", "--restore", "backup.csv", "--interactive"]),
            &f,
        );
        let launched = f.launched.borrow();
        let a = &launched[0].1;
        assert_eq!(a[..2], ["audit-policy", "--restore"]);
        assert!(
            Path::new(&a[2]).is_absolute() && a[2].ends_with(r"\backup.csv"),
            "{a:?}"
        );
        assert_eq!(a[3..], ["--interactive"]);
    }

    #[test]
    fn a_copy_started_by_this_same_exe_never_relaunches_again() {
        // If "runas" ever starts the copy without elevation (UAC turned off for a standard user),
        // the copy must not start yet another copy: no endless chain of waiting processes.
        // Without a relaunch the real install plan runs; it must stop at require_admin.
        if crate::winutil::skip_when_elevated(
            "a_copy_started_by_this_same_exe_never_relaunches_again",
            "would run the real install plan past require_admin",
        ) {
            return;
        }
        let mut f = FakeElevator::new(false, Ok(0));
        f.parent_is_same_exe = true;
        run_with(args(&["install", "--interactive"]), &f);
        assert!(f.launched.borrow().is_empty());
    }

    #[test]
    fn a_refused_elevation_shows_an_error_box_and_exits_1() {
        let f = FakeElevator::new(false, Err("관리자 권한 요청이 취소되었습니다.".to_string()));
        assert_eq!(run_with(args(&["uninstall", "--interactive"]), &f), 1);
        assert_eq!(*f.boxes.borrow(), ["관리자 권한 요청이 취소되었습니다."]);
    }

    #[test]
    fn nothing_else_is_ever_elevated() {
        // Some of these run an install plan on this PC: it stops at require_admin (not elevated).
        crate::winutil::assert_not_elevated();
        for (elevated, a) in [
            (true, &["install", "--interactive"][..]),
            (false, &["install", "--interactive", "--dry-run"][..]),
            (false, &["install"][..]),
            (false, &["uninstall", "--dry-run", "--interactive"][..]),
            (false, &["audit-policy", "--enable"][..]),
            (false, &["app"][..]),
            (false, &["app", "--background"][..]),
            (false, &["agent", "--server", "http://127.0.0.1:8700"][..]),
            (false, &["autostart", "on"][..]),
            (false, &[][..]),
            (false, &["--version"][..]),
        ] {
            // An elevated process would get past require_admin and run the real plan.
            let real_plan = matches!(a.first(), Some(&"install" | &"audit-policy"))
                && !a.contains(&"--dry-run");
            if real_plan
                && crate::winutil::skip_when_elevated(
                    &format!("nothing_else_is_ever_elevated {a:?}"),
                    "would run the real install plan",
                )
            {
                continue;
            }
            let f = FakeElevator::new(elevated, Ok(0));
            run_with(args(a), &f);
            assert!(f.launched.borrow().is_empty(), "{a:?}");
        }
    }

    #[test]
    fn an_interactive_installer_run_reports_in_a_message_box() {
        // Not elevated: the plan stops at require_admin before it changes anything.
        if crate::winutil::skip_when_elevated(
            "an_interactive_installer_run_reports_in_a_message_box",
            "would run the real install plan past require_admin",
        ) {
            return;
        }
        let dir = crate::install::testutil::Scratch::new();
        let inst = dir.path().join("i");
        let data = dir.path().join("d");
        let (inst, data) = (inst.to_str().unwrap(), data.to_str().unwrap());
        // `elevated: true` = no relaunch; the plan itself still sees this process is not elevated.
        let f = FakeElevator::new(true, Ok(0));
        let a = [
            "install",
            "--install-dir",
            inst,
            "--data-root",
            data,
            "--interactive",
        ];
        assert_eq!(run_with(args(&a), &f), 1);
        assert_eq!(*f.boxes.borrow(), [install::plan::ADMIN_MESSAGE]);
        assert!(!dir.path().join("i").exists() && !dir.path().join("d").exists());
        let f = FakeElevator::new(true, Ok(0));
        let a = [
            "install",
            "--install-dir",
            inst,
            "--data-root",
            inst,
            "--interactive",
        ];
        assert_eq!(run_with(args(&a), &f), 2);
        assert!(
            f.boxes.borrow()[0].starts_with("오류: --data-root: "),
            "{:?}",
            f.boxes.borrow()
        );
        // Without --interactive nothing is shown in a box.
        let f = FakeElevator::new(false, Ok(0));
        assert_eq!(
            run_with(args(&["audit-policy", "--enable", "--data-root", data]), &f),
            1
        );
        assert!(f.boxes.borrow().is_empty() && f.launched.borrow().is_empty());
    }

    #[test]
    fn the_failure_box_shows_the_last_failure_line_and_success_names_the_port() {
        assert_eq!(
            failure_text("[1/2] a\n[2/2] b\n[실패] b: 종료 코드 5\n".as_bytes()),
            "[실패] b: 종료 코드 5"
        );
        assert_eq!(
            failure_text("[1/1] require_admin\n관리자 권한으로 다시 실행하세요.\n\n".as_bytes()),
            "관리자 권한으로 다시 실행하세요."
        );
        assert_eq!(failure_text(b""), "실패했습니다.");
        // Review item 4: the recovery line after the failure is shown too.
        assert_eq!(
            failure_text("[3/9] stop_apps\n[실패] stop_apps: x\n[복구] 이전 버전의 서비스를 다시 시작했습니다(sc.exe start mcp-monitor).\n".as_bytes()),
            "[실패] stop_apps: x\n[복구] 이전 버전의 서비스를 다시 시작했습니다(sc.exe start mcp-monitor)."
        );
        let mut plan = Plan {
            script: "install".into(),
            version: None,
            layout: None,
            install_dir: None,
            data_root: None,
            service_mode: None,
            steps: vec![install::plan::Step::new(
                "install_info",
                "(write-json)",
                vec!["x".into(), r#"{"local_port":9700}"#.into()],
            )],
            notes: vec![],
        };
        assert_eq!(
            install_done_line(&plan),
            "설치 완료: http://127.0.0.1:9700/admin/setup 에서 첫 Admin 계정을 만드세요."
        );
        plan.steps.clear();
        assert!(install_done_line(&plan).contains("127.0.0.1:8700/"));
    }

    #[test]
    fn the_uninstall_line_says_where_the_data_stays_and_what_waits_for_a_restart() {
        let plan = Plan {
            script: "uninstall".into(),
            version: None,
            layout: None,
            install_dir: Some(r"C:\Program Files\MCP Monitor".into()),
            data_root: Some(r"D:\MCP Data".into()),
            service_mode: None,
            steps: vec![],
            notes: vec![],
        };
        assert_eq!(
            uninstall_done_line(&plan, false, false),
            r"제거 완료. 데이터는 D:\MCP Data 에 남아 있습니다(지우려면 --remove-data)."
        );
        assert_eq!(
            uninstall_done_line(&plan, true, false),
            "제거 완료(데이터 포함)."
        );
        assert_eq!(
            uninstall_done_line(&plan, true, true),
            "제거 완료(데이터 포함).\n설치 폴더의 남은 파일은 다시 시작할 때 지워집니다."
        );
    }

    /// An argument error never runs anything: `오류: …`, 2, and with `--interactive` a box.
    #[test]
    fn an_uninstall_argument_error_exits_2_and_shows_a_box_when_interactive() {
        let dir = crate::install::testutil::Scratch::new();
        let inst = dir.path().join("i");
        let data = inst.join("var");
        let (inst, data) = (inst.to_str().unwrap(), data.to_str().unwrap());
        // `elevated: true` = no relaunch.
        let f = FakeElevator::new(true, Ok(0));
        let a = [
            "uninstall",
            "--install-dir",
            inst,
            "--data-root",
            data,
            "--interactive",
        ];
        assert_eq!(run_with(args(&a), &f), 2);
        let boxes = f.boxes.borrow();
        assert!(
            boxes.len() == 1 && boxes[0].contains("--remove-data로 함께 지우기"),
            "{boxes:?}"
        );
        let f = FakeElevator::new(false, Ok(0));
        let a = [
            "uninstall",
            "--dry-run",
            "--install-dir",
            inst,
            "--data-root",
            data,
            "--remove-data",
        ];
        assert_eq!(run_with(args(&a), &f), 0);
        assert!(f.boxes.borrow().is_empty() && f.launched.borrow().is_empty());
    }

    #[test]
    fn verify_payload_refuses_a_folder_that_is_not_empty_or_not_a_folder() {
        let f = FakeElevator::new(false, Ok(0));
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("x.txt"), "x").unwrap();
        let shown = dir.path().to_str().unwrap();
        assert_eq!(run_with(args(&["verify-payload", shown]), &f), 2);
        assert!(!dir.path().join("payload").exists());
        let file = dir.path().join("x.txt");
        assert_eq!(
            run_with(args(&["verify-payload", file.to_str().unwrap()]), &f),
            2
        );
    }

    #[test]
    fn verify_payload_extracts_into_a_new_or_empty_folder() {
        let f = FakeElevator::new(false, Ok(0));
        let dir = tempfile::tempdir().unwrap();
        let missing = dir.path().join("new");
        assert_eq!(
            run_with(args(&["verify-payload", missing.to_str().unwrap()]), &f),
            0
        );
        let files = payload::manifest().files;
        for file in &files {
            assert!(
                missing.join("payload").join(&file.path).is_file(),
                "{}",
                file.path
            );
        }
        let empty = dir.path().join("empty");
        std::fs::create_dir(&empty).unwrap();
        assert_eq!(
            run_with(args(&["verify-payload", empty.to_str().unwrap()]), &f),
            0
        );
        assert!(empty.join("payload/bundle.json").is_file());
    }

    /// An install folder with `install.json` (local port 9700) and, when `exe`, `mcp-monitor.exe`.
    fn install_folder(exe: bool) -> tempfile::TempDir {
        let d = tempfile::tempdir().unwrap();
        std::fs::write(
            d.path().join("install.json"),
            r#"{"version":"1.1.0","local_port":9700,"external_port":9701,"data_root":"D:\\MCP"}"#,
        )
        .unwrap();
        if exe {
            std::fs::write(d.path().join("mcp-monitor.exe"), "x").unwrap();
        }
        d
    }

    fn entry(version: &str, dir: &Path) -> Installed {
        Installed {
            version: version.into(),
            install_location: dir.to_path_buf(),
        }
    }

    fn strings(v: &[&str]) -> Vec<String> {
        v.iter().map(|x| x.to_string()).collect()
    }

    #[test]
    fn auto_on_a_new_pc_asks_to_install_and_no_ends_it() {
        let f = FakeElevator::new(false, Ok(0));
        assert_eq!(run_with(args(&[]), &f), 0);
        assert_eq!(
            *f.asked.borrow(),
            [app::install_prompt(
                Some(Path::new(r"C:\Program Files\MCP Monitor")),
                Some(Path::new(r"C:\ProgramData\MCP Monitor"))
            )]
        );
        assert!(f.launched.borrow().is_empty() && f.windows.borrow().is_empty());
        assert!(f.started.borrow().is_empty() && f.boxes.borrow().is_empty());
    }

    #[test]
    fn auto_installs_elevated_then_starts_the_installed_copy() {
        let dir = install_folder(true);
        let mut f = FakeElevator::new(false, Ok(0));
        f.yes = true;
        f.installs_to = Some(entry("1.1.0", dir.path()));
        assert_eq!(run_with(args(&[]), &f), 0);
        assert_eq!(
            *f.launched.borrow(),
            [(f.exe.clone(), strings(&["install", "--interactive"]))]
        );
        // F27: the download does not stay open as the tray; the installed exe does.
        assert_eq!(*f.started.borrow(), [dir.path().join("mcp-monitor.exe")]);
        assert!(f.windows.borrow().is_empty() && f.boxes.borrow().is_empty());
    }

    #[test]
    fn auto_opens_the_window_itself_when_the_installed_exe_is_not_there() {
        let dir = install_folder(false);
        let mut f = FakeElevator::new(false, Ok(0));
        f.yes = true;
        f.installs_to = Some(entry("1.1.0", dir.path()));
        assert_eq!(run_with(args(&[]), &f), 0);
        assert!(f.started.borrow().is_empty());
        let windows = f.windows.borrow();
        assert_eq!(windows.len(), 1);
        assert_eq!((windows[0].0.info.local_port, windows[0].1), (9700, false));
    }

    #[test]
    fn auto_stops_when_the_installer_fails_or_uac_is_refused() {
        for (answer, code, boxes) in [
            (Ok(1), 1, 0),
            (Err(winutil::ELEVATION_CANCELLED.to_string()), 0, 0),
            (
                Err("관리자 권한으로 다시 실행하지 못했습니다: x".to_string()),
                1,
                1,
            ),
        ] {
            let mut f = FakeElevator::new(false, answer.clone());
            f.yes = true;
            assert_eq!(run_with(args(&[]), &f), code, "{answer:?}");
            assert_eq!(f.launched.borrow().len(), 1);
            assert_eq!(f.boxes.borrow().len(), boxes, "{answer:?}");
            assert!(f.windows.borrow().is_empty() && f.started.borrow().is_empty());
        }
    }

    #[test]
    fn auto_upgrades_an_older_install_in_its_own_folder() {
        let dir = install_folder(true);
        let mut f = FakeElevator::new(false, Ok(0));
        *f.installed.borrow_mut() = Some(entry("1.0.0", dir.path()));
        f.service = true;
        f.yes = true;
        f.installs_to = Some(entry("1.1.0", dir.path()));
        assert_eq!(run_with(args(&[]), &f), 0);
        assert_eq!(
            *f.asked.borrow(),
            [app::upgrade_prompt(
                Some(version::Version(1, 0, 0)),
                version::product()
            )]
        );
        let shown = dir.path().display().to_string();
        assert_eq!(
            f.launched.borrow()[0].1,
            strings(&["install", "--install-dir", &shown, "--interactive"])
        );
        assert_eq!(*f.started.borrow(), [dir.path().join("mcp-monitor.exe")]);
    }

    #[test]
    fn auto_upgrades_a_powershell_install_found_through_its_service() {
        // 1.0.0: no Apps & features entry, the version in bundle.json, the folder in the binPath.
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("bundle.json"), r#"{"version":"1.0.0"}"#).unwrap();
        let mut f = FakeElevator::new(false, Ok(0));
        f.service = true;
        f.bin_path = Some(format!(
            r#""{}\bin\monitor\mcp-monitor.exe" service --root "D:\MCP""#,
            dir.path().display()
        ));
        assert_eq!(run_with(args(&[]), &f), 0, "no: nothing happens");
        assert!(f.asked.borrow()[0].starts_with("설치된 MCP Monitor 1.0.0을(를) "));
        assert!(f.launched.borrow().is_empty());
        f.yes = true;
        run_with(args(&[]), &f);
        let shown = dir.path().display().to_string();
        assert_eq!(
            f.launched.borrow()[0].1,
            strings(&["install", "--install-dir", &shown, "--interactive"])
        );
    }

    #[test]
    fn auto_with_the_same_version_opens_the_installed_window_without_asking() {
        let dir = install_folder(true);
        let mut f = FakeElevator::new(false, Ok(0));
        *f.installed.borrow_mut() = Some(entry("1.1.0", dir.path()));
        f.service = true;
        // from a download: the installed copy is started
        assert_eq!(run_with(args(&[]), &f), 0);
        assert_eq!(*f.started.borrow(), [dir.path().join("mcp-monitor.exe")]);
        // the installed copy itself (the Start menu shortcut): its own window
        f.exe = dir.path().join("MCP-MONITOR.EXE");
        f.started.borrow_mut().clear();
        assert_eq!(run_with(args(&[]), &f), 0);
        assert!(f.started.borrow().is_empty());
        assert_eq!(f.windows.borrow().len(), 1);
        assert!(f.asked.borrow().is_empty() && f.launched.borrow().is_empty());
    }

    #[test]
    fn auto_refuses_to_downgrade_and_opens_the_newer_install() {
        let dir = install_folder(true);
        let mut f = FakeElevator::new(false, Ok(0));
        *f.installed.borrow_mut() = Some(entry("9.0.0", dir.path()));
        f.service = true;
        assert_eq!(run_with(args(&[]), &f), 0);
        assert_eq!(
            *f.boxes.borrow(),
            [format!(
                "info: {}",
                app::older_notice(version::Version(9, 0, 0), version::product())
            )]
        );
        assert!(f.launched.borrow().is_empty() && f.asked.borrow().is_empty());
        assert_eq!(*f.started.borrow(), [dir.path().join("mcp-monitor.exe")]);
    }

    #[test]
    fn auto_offers_a_repair_install_when_the_service_is_gone() {
        let dir = install_folder(true);
        let f = FakeElevator::new(false, Ok(0));
        *f.installed.borrow_mut() = Some(entry("1.1.0", dir.path()));
        assert_eq!(run_with(args(&[]), &f), 0);
        assert_eq!(
            *f.asked.borrow(),
            [app::install_prompt(
                Some(dir.path()),
                Some(Path::new(r"D:\MCP"))
            )]
        );
    }

    #[test]
    fn app_opens_the_installed_servers_window_or_says_it_is_not_installed() {
        let f = FakeElevator::new(false, Ok(0));
        assert_eq!(run_with(args(&["app"]), &f), 1);
        assert_eq!(*f.boxes.borrow(), [app::NOT_INSTALLED]);
        assert!(f.windows.borrow().is_empty());

        let dir = install_folder(true);
        let f = FakeElevator::new(false, Ok(0));
        *f.installed.borrow_mut() = Some(entry("1.1.0", dir.path()));
        assert_eq!(run_with(args(&["app", "--background"]), &f), 0);
        {
            let windows = f.windows.borrow();
            assert_eq!(
                (
                    windows[0].0.info.local_port,
                    windows[0].0.install_dir.as_deref(),
                    windows[0].1
                ),
                (9700, Some(dir.path()), true)
            );
        }
        assert!(f.started.borrow().is_empty() && f.launched.borrow().is_empty());

        // no Apps & features entry: the exe's own folder when it holds install.json
        let mut f = FakeElevator::new(false, Ok(0));
        f.exe = dir.path().join("mcp-monitor.exe");
        assert_eq!(run_with(args(&["app"]), &f), 0);
        assert_eq!(f.windows.borrow()[0].0.info.local_port, 9700);
    }

    /// Review item 17 (F06): the installed copy started with no arguments while the service is gone
    /// would offer an install that its own `(stage)` step refuses: it says why instead, without a
    /// UAC prompt.
    #[test]
    fn the_installed_copy_does_not_offer_an_install_it_cannot_do() {
        let dir = install_folder(true);
        let mut f = FakeElevator::new(false, Ok(0));
        *f.installed.borrow_mut() = Some(entry("1.1.0", dir.path()));
        f.exe = dir.path().join("mcp-monitor.exe");
        f.yes = true;
        assert_eq!(run_with(args(&[]), &f), 1);
        assert!(f.asked.borrow().is_empty() && f.launched.borrow().is_empty());
        let boxes = f.boxes.borrow();
        assert!(
            boxes.len() == 1 && boxes[0].contains("다운로드한 mcp-monitor-1.1.0.exe로 실행하세요"),
            "{boxes:?}"
        );
    }

    /// Review item 18: the window, the tray and its autostart item run with the user's own token,
    /// never an administrator's ("관리자 권한으로 실행" on the download, an elevated shell). Elevated,
    /// `app` and the no-argument start open nothing and start nothing: a box says how to open it.
    #[test]
    fn an_elevated_process_never_opens_the_window_or_starts_the_app() {
        let dir = install_folder(true);
        for a in [&["app"][..], &["app", "--background"][..], &[][..]] {
            let mut f = FakeElevator::new(true, Ok(0));
            *f.installed.borrow_mut() = Some(entry("1.1.0", dir.path()));
            f.service = true;
            assert_eq!(run_with(args(a), &f), 1, "{a:?}");
            assert!(
                f.windows.borrow().is_empty() && f.started.borrow().is_empty(),
                "{a:?}"
            );
            assert_eq!(*f.boxes.borrow(), [app::ELEVATED_APP], "{a:?}");
        }
    }

    /// The one exception: a development build attached to a development server (`--server-url`
    /// parses only with the `dev` feature), which the elevated CI runner uses for its window tests.
    #[cfg(feature = "dev")]
    #[test]
    fn an_elevated_development_build_still_opens_a_development_server() {
        let f = FakeElevator::new(true, Ok(0));
        assert_eq!(
            run_with(args(&["app", "--server-url", "http://127.0.0.1:9700"]), &f),
            0
        );
        assert_eq!(f.windows.borrow().len(), 1);
        assert!(f.boxes.borrow().is_empty());
    }

    #[test]
    fn autostart_writes_the_run_value_of_the_installed_copy_only() {
        let f = FakeElevator::new(false, Ok(0));
        assert_eq!(run_with(args(&["autostart", "on"]), &f), 1);
        assert!(f.autostart.borrow().is_empty());

        let dir = Path::new(r"C:\Program Files\MCP Monitor");
        let f = FakeElevator::new(false, Ok(0));
        *f.installed.borrow_mut() = Some(entry("1.1.0", dir));
        assert_eq!(run_with(args(&["autostart", "on"]), &f), 0);
        assert_eq!(run_with(args(&["autostart", "off"]), &f), 0);
        assert_eq!(
            *f.autostart.borrow(),
            [(dir.to_path_buf(), true), (dir.to_path_buf(), false)]
        );
        assert!(f.launched.borrow().is_empty());

        let mut f = FakeElevator::new(false, Ok(0));
        *f.installed.borrow_mut() = Some(entry("1.1.0", dir));
        f.autostart_fails = true;
        assert_eq!(run_with(args(&["autostart", "off"]), &f), 1);
    }
}
