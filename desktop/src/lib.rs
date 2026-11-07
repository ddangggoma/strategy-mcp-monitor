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

/// What [`run_with`] needs from Windows to re-run itself elevated. The real one is
/// [`SystemElevator`]; tests use a fake, so no test ever shows a UAC prompt or a message box.
pub trait Elevator {
    fn is_elevated(&self) -> bool;
    /// True in the copy that a relaunch started (see [`winutil::parent_is_same_exe`]).
    fn parent_is_same_exe(&self) -> bool;
    fn current_exe(&self) -> std::io::Result<PathBuf>;
    fn elevate_and_wait(&self, exe: &Path, args: &[String]) -> Result<i32, String>;
    fn error_box(&self, text: &str);
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
    }

    fn args(v: &[&str]) -> Vec<OsString> {
        v.iter().map(OsString::from).collect()
    }

    #[test]
    fn version_flag_exits_0_and_unsupported_or_bad_commands_exit_2() {
        let f = FakeElevator::new(false, Ok(0));
        assert_eq!(run_with(args(&["--version"]), &f), 0);
        assert_eq!(run_with(args(&[]), &f), 2);
        assert_eq!(run_with(args(&["install"]), &f), 2);
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
            let f = FakeElevator::new(elevated, Ok(0));
            run_with(args(a), &f);
            assert!(f.launched.borrow().is_empty(), "{a:?}");
        }
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
