mod common;
use common::run;

#[test]
fn version_prints_one_line() {
    let o = run(&["--version"]);
    assert!(o.status.success());
    let line = String::from_utf8(o.stdout).unwrap();
    let re = regex::Regex::new(
        r"^mcp-monitor 1\.1\.0 \(payload [0-9a-f]{12}, (fixture|release)(, dev)?\)\r?\n$",
    )
    .unwrap();
    assert!(re.is_match(&line), "{line:?}");
    let payload = mcp_monitor::payload::ARCHIVE_SHA256;
    assert!(
        line.contains(&format!("(payload {}, ", &payload[..12])),
        "{line:?}"
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
fn modes_of_later_tasks_are_not_supported_yet() {
    let o = run(&["uninstall", "--dry-run"]);
    assert_eq!(o.status.code(), Some(2));
    assert_eq!(
        String::from_utf8(o.stderr).unwrap().trim_end(),
        "오류: 아직 지원하지 않는 명령입니다"
    );
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
