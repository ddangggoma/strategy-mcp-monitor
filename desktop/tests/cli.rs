mod common;
use common::run;
use std::io::Read;
use std::process::Stdio;

const VERSION_LINE: &str =
    r"^mcp-monitor 1\.0\.0 \(payload [0-9a-f]{12}, (fixture|release)(, dev)?\)\r?\n$";

fn assert_version_line(line: &str) {
    assert!(
        regex::Regex::new(VERSION_LINE).unwrap().is_match(line),
        "{line:?}"
    );
}

#[test]
fn version_prints_one_line() {
    let o = run(&["--version"]);
    assert!(o.status.success());
    let line = String::from_utf8(o.stdout).unwrap();
    assert_version_line(&line);
    let payload = mcp_monitor::payload::ARCHIVE_SHA256;
    assert!(
        line.contains(&format!("(payload {}, ", &payload[..12])),
        "{line:?}"
    );
}

// The exe is GUI-subsystem: its standard output must work through a pipe and a file it was
// handed, and a stdout that cannot be written must never crash it or change its exit code.

#[test]
fn version_prints_through_a_pipe() {
    let mut child = common::exe()
        .arg("--version")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let mut line = String::new();
    child
        .stdout
        .take()
        .unwrap()
        .read_to_string(&mut line)
        .unwrap();
    let o = child.wait_with_output().unwrap();
    assert_eq!(
        o.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&o.stderr)
    );
    assert_version_line(&line);
    assert!(
        o.stderr.is_empty(),
        "{}",
        String::from_utf8_lossy(&o.stderr)
    );
}

#[test]
fn version_prints_into_a_file() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("version.txt");
    let file = std::fs::File::create(&path).unwrap();
    let o = common::exe()
        .arg("--version")
        .stdin(Stdio::null())
        .stdout(file)
        .stderr(Stdio::piped())
        .output()
        .unwrap();
    assert_eq!(
        o.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&o.stderr)
    );
    assert_version_line(&std::fs::read_to_string(&path).unwrap());
}

#[test]
fn argument_errors_go_into_a_file_too() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("errors.txt");
    let file = std::fs::File::create(&path).unwrap();
    let o = common::exe()
        .arg("nope")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(file)
        .output()
        .unwrap();
    assert_eq!(o.status.code(), Some(2));
    assert!(o.stdout.is_empty());
    let err = std::fs::read_to_string(&path).unwrap();
    assert!(err.starts_with("오류: "), "{err:?}");
}

#[test]
fn a_closed_stdout_neither_crashes_nor_changes_the_exit_code() {
    // The reader is gone before the exe starts: every write to stdout fails with
    // ERROR_NO_DATA (232, "The pipe is being closed"), where `println!` would panic.
    let s = common::Scratch::new();
    let (inst, data) = (s.join("i"), s.join("d"));
    let (inst, data) = (inst.to_str().unwrap(), data.to_str().unwrap());
    let dry_run = [
        "install",
        "--dry-run",
        "--install-dir",
        inst,
        "--data-root",
        data,
    ];
    for (args, code) in [
        (&["--version"][..], 0),
        (&dry_run[..], 0),
        (&["nope"][..], 2),
    ] {
        let (reader, writer) = std::io::pipe().unwrap();
        drop(reader);
        let o = common::exe()
            .args(args)
            .stdin(Stdio::null())
            .stdout(writer)
            .stderr(Stdio::piped())
            .output()
            .unwrap();
        let err = String::from_utf8_lossy(&o.stderr);
        assert_eq!(o.status.code(), Some(code), "{args:?}: {err}");
        assert!(!err.contains("panicked"), "{args:?}: {err}");
    }
}

#[test]
fn a_null_stdout_is_fine() {
    let o = common::exe()
        .arg("--version")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .output()
        .unwrap();
    assert_eq!(
        o.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&o.stderr)
    );
    assert!(
        o.stderr.is_empty(),
        "{}",
        String::from_utf8_lossy(&o.stderr)
    );
}

#[test]
fn argument_errors_exit_2_in_korean() {
    for args in [
        &["install", "--bogus"][..],
        &[
            "agent",
            "--server",
            "http://127.0.0.1:8700",
            "--dialog",
            "edge",
        ][..],
        &["nope"][..],
    ] {
        let o = run(args);
        assert_eq!(o.status.code(), Some(2), "{args:?}");
        assert!(o.stdout.is_empty());
        assert!(
            String::from_utf8(o.stderr).unwrap().starts_with("오류: "),
            "{args:?}"
        );
    }
}

#[test]
fn autostart_without_an_install_exits_1_and_writes_nothing() {
    // With an Apps & features entry this would write this user's real `Run` value (Y23: never).
    let entry = mcp_monitor::install::host::UNINSTALL_KEY;
    let installed = {
        use mcp_monitor::install::registry::Registry;
        mcp_monitor::install::registry::WinRegistry
            .string(entry, "InstallLocation")
            .is_some()
    };
    if installed {
        println!("SKIPPED autostart_without_an_install_exits_1_and_writes_nothing: {entry} exists");
        return;
    }
    for on in ["on", "off"] {
        let o = run(&["autostart", on]);
        assert_eq!(o.status.code(), Some(1), "{on}");
        assert!(o.stdout.is_empty(), "{on}");
        let err = String::from_utf8(o.stderr).unwrap();
        assert!(
            err.starts_with("오류: MCP Monitor가 설치되어 있지 않습니다"),
            "{err:?}"
        );
    }
    let o = run(&["autostart"]);
    assert_eq!(o.status.code(), Some(2));
}

#[test]
fn verify_payload_extracts_and_checks_the_embedded_server() {
    let s = common::Scratch::new();
    let o = run(&["verify-payload", s.path().to_str().unwrap()]);
    assert_eq!(
        o.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&o.stderr)
    );
    assert!(
        String::from_utf8(o.stdout)
            .unwrap()
            .starts_with("payload OK: ")
    );
    assert!(
        s.join("payload/bin/monitor/mcp-monitor-server.exe")
            .is_file()
    );
}

#[test]
fn verify_payload_counts_files_and_bytes_and_creates_a_missing_folder() {
    let s = common::Scratch::new();
    let target = s.join("v");
    let o = run(&["verify-payload", target.to_str().unwrap()]);
    assert_eq!(
        o.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&o.stderr)
    );
    let m = mcp_monitor::payload::manifest();
    let bytes: u64 = m.files.iter().map(|f| f.size).sum();
    assert_eq!(
        String::from_utf8(o.stdout).unwrap().trim_end(),
        format!("payload OK: {} files, {bytes} bytes", m.files.len())
    );
    assert!(target.join("payload/bundle.json").is_file());
}

#[test]
fn verify_payload_refuses_a_folder_that_is_not_empty() {
    let s = common::Scratch::new();
    std::fs::write(s.join("keep.txt"), "mine").unwrap();
    let o = run(&["verify-payload", s.path().to_str().unwrap()]);
    assert_eq!(o.status.code(), Some(2));
    assert!(o.stdout.is_empty());
    let err = String::from_utf8(o.stderr).unwrap();
    assert!(
        err.starts_with("오류: ") && err.contains("비어 있지 않습니다"),
        "{err:?}"
    );
    assert!(!s.join("payload").exists());
    assert_eq!(std::fs::read_to_string(s.join("keep.txt")).unwrap(), "mine");
}
