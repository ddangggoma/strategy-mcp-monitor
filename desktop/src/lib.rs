//! MCP Monitor desktop executable: one GUI-subsystem exe whose first argument picks the mode.

use std::ffi::OsString;
use std::path::{Path, PathBuf};

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

pub fn run_with(args: Vec<OsString>, elevator: &dyn Elevator) -> i32 {
    let cmd = match decode_args(args).and_then(|a| cli::parse(&a)) {
        Ok(cmd) => cmd,
        Err(e) => {
            eprintln!("오류: {}", e.0);
            return 2;
        }
    };
    if cli::needs_relaunch(&cmd, elevator.is_elevated()) && !elevator.parent_is_same_exe() {
        return relaunch_elevated(&cmd, elevator);
    }
    match cmd {
        Command::Version => {
            println!(
                "{}",
                version::version_line(
                    version::PRODUCT,
                    payload::ARCHIVE_SHA256,
                    payload::KIND,
                    cfg!(feature = "dev")
                )
            );
            0
        }
        Command::VerifyPayload(dir) => verify_payload(&dir),
        Command::Install(a) => {
            let host = SystemHost::new();
            let built = install::install_plan::build_install_plan(&a, &host);
            run_installer(
                built,
                a.dry_run,
                a.interactive,
                &host,
                elevator,
                install_done_line,
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
            run_installer(built, a.dry_run, a.interactive, &host, elevator, |_| {
                done.to_string()
            })
        }
        _ => {
            eprintln!("오류: 아직 지원하지 않는 명령입니다");
            2
        }
    }
}

/// Re-runs this same exe elevated with arguments rebuilt from the parsed command (absolute paths,
/// no `--dry-run`, `--interactive` last) and returns its exit code; errors go to a message box + 1.
fn relaunch_elevated(cmd: &Command, elevator: &dyn Elevator) -> i32 {
    let cmd = match cli::with_absolute_paths(cmd, |p| std::path::absolute(p)) {
        Ok(cmd) => cmd,
        Err(e) => {
            eprintln!("오류: {}", e.0);
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

/// Standard output through `print!` (`Stderr`: `eprint!`), so the test harness captures what a
/// plan prints like any other `println!`. Every write is a whole `&str` piece of a `writeln!`.
struct Stdout;
struct Stderr;

impl Write for Stdout {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        print!("{}", String::from_utf8_lossy(buf));
        Ok(buf.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        std::io::stdout().flush()
    }
}

impl Write for Stderr {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        eprint!("{}", String::from_utf8_lossy(buf));
        Ok(buf.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
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
    lines
        .iter()
        .rev()
        .find(|l| l.starts_with("[실패]"))
        .or(lines.last())
        .map_or_else(|| "실패했습니다.".to_string(), |l| l.to_string())
}

/// `install` / `audit-policy` after the plan is built: argument errors are `오류: …` + 2,
/// `--dry-run` prints the plan, otherwise the plan runs (0, or 1 at the first failure). With
/// `--interactive` the result is also shown in a message box.
fn run_installer(
    built: Result<Plan, ArgError>,
    dry_run: bool,
    interactive: bool,
    host: &dyn Host,
    elevator: &dyn Elevator,
    done: impl Fn(&Plan) -> String,
) -> i32 {
    let plan = match built {
        Ok(plan) => plan,
        Err(e) => {
            eprintln!("오류: {}", e.0);
            if interactive {
                elevator.error_box(&format!("오류: {}", e.0));
            }
            return 2;
        }
    };
    if dry_run {
        return print_dry_run(&plan, &mut Stdout, &mut Stderr);
    }
    let mut ex = RealExecutor::new(&plan, host, SystemRunner, Stdout);
    let mut out = Tee {
        inner: Stdout,
        copy: Vec::new(),
    };
    let code = run_plan(&plan, &mut ex, &mut out);
    if code == 0 {
        let line = done(&plan);
        println!("{line}");
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
            eprintln!("오류: {}은(는) 폴더가 아닙니다", dir.display());
            return 2;
        }
        match std::fs::read_dir(dir) {
            Ok(mut entries) => {
                if entries.next().is_some() {
                    eprintln!("오류: {}이(가) 비어 있지 않습니다", dir.display());
                    return 2;
                }
            }
            Err(e) => {
                eprintln!("오류: {} 폴더를 읽을 수 없습니다: {e}", dir.display());
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
            println!("payload OK: {files} files, {bytes} bytes");
            0
        }
        Err(e) => {
            println!("[실패] verify-payload: {e}");
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

    use std::cell::RefCell;
    use std::os::windows::ffi::OsStringExt;
    use std::path::{Path, PathBuf};

    /// Records what `run_with` asks for; never shows a UAC prompt or a message box.
    struct FakeElevator {
        elevated: bool,
        parent_is_same_exe: bool,
        answer: Result<i32, String>,
        launched: RefCell<Vec<(PathBuf, Vec<String>)>>,
        boxes: RefCell<Vec<String>>,
    }

    impl FakeElevator {
        fn new(elevated: bool, answer: Result<i32, String>) -> FakeElevator {
            FakeElevator {
                elevated,
                parent_is_same_exe: false,
                answer,
                launched: RefCell::new(Vec::new()),
                boxes: RefCell::new(Vec::new()),
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
            Ok(PathBuf::from(r"C:\Users\u\Downloads\mcp-monitor-1.1.0.exe"))
        }
        fn elevate_and_wait(&self, exe: &Path, args: &[String]) -> Result<i32, String> {
            self.launched
                .borrow_mut()
                .push((exe.to_path_buf(), args.to_vec()));
            self.answer.clone()
        }
        fn error_box(&self, text: &str) {
            self.boxes.borrow_mut().push(text.to_string());
        }
        fn info_box(&self, text: &str) {
            self.boxes.borrow_mut().push(format!("info: {text}"));
        }
    }

    fn args(v: &[&str]) -> Vec<OsString> {
        v.iter().map(OsString::from).collect()
    }

    #[test]
    fn version_flag_exits_0_and_unsupported_or_bad_commands_exit_2() {
        let f = FakeElevator::new(false, Ok(0));
        assert_eq!(run_with(args(&["--version"]), &f), 0);
        assert_eq!(run_with(args(&[]), &f), 2);
        assert_eq!(run_with(args(&["uninstall"]), &f), 2);
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
}
