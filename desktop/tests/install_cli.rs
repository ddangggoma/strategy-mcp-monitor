mod common;
use common::*;

#[test]
fn install_dry_run_prints_one_json_line() {
    mcp_monitor::winutil::assert_not_elevated();
    let s = Scratch::new();
    let o = exe()
        .args(["install", "--dry-run", "--install-dir"])
        .arg(s.join("i"))
        .arg("--data-root")
        .arg(s.join("d"))
        .output()
        .unwrap();
    assert_eq!(
        o.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&o.stderr)
    );
    let text = String::from_utf8(o.stdout).unwrap();
    assert_eq!(text.lines().count(), 1);
    let plan: serde_json::Value = serde_json::from_str(&text).unwrap();
    assert_eq!(
        (plan["script"].as_str(), plan["steps"][0]["id"].as_str()),
        (Some("install"), Some("require_admin"))
    );
    assert!(!s.join("i").exists() && !s.join("d").exists());
}

#[test]
fn install_without_admin_exits_1_and_changes_nothing() {
    if mcp_monitor::winutil::skip_when_elevated(
        "install_without_admin_exits_1_and_changes_nothing",
        "an elevated install would get past require_admin",
    ) {
        return;
    }
    let s = Scratch::new();
    let o = exe()
        .args(["install", "--install-dir"])
        .arg(s.join("i"))
        .arg("--data-root")
        .arg(s.join("d"))
        .output()
        .unwrap();
    assert_eq!(
        o.status.code(),
        Some(1),
        "{}",
        String::from_utf8_lossy(&o.stderr)
    );
    assert!(
        String::from_utf8(o.stdout)
            .unwrap()
            .contains("관리자 권한으로 다시 실행하세요")
    );
    assert!(!s.join("i").exists() && !s.join("d").exists() && !s.join("i.staging").exists());
}

#[test]
fn audit_policy_without_admin_exits_1_and_changes_nothing() {
    if mcp_monitor::winutil::skip_when_elevated(
        "audit_policy_without_admin_exits_1_and_changes_nothing",
        "an elevated run would change the runner's audit policy",
    ) {
        return;
    }
    let s = Scratch::new();
    let o = exe()
        .args(["audit-policy", "--enable", "--data-root"])
        .arg(s.join("d"))
        .output()
        .unwrap();
    assert_eq!(o.status.code(), Some(1));
    assert!(!s.join("d").exists());
}

#[test]
fn install_argument_errors_print_nothing_on_stdout() {
    let s = Scratch::new();
    let o = exe()
        .args([
            "install",
            "--dry-run",
            "--local-port",
            "8800",
            "--external-port",
            "8800",
            "--install-dir",
        ])
        .arg(s.join("i"))
        .output()
        .unwrap();
    assert_eq!(o.status.code(), Some(2));
    assert!(
        o.stdout.is_empty()
            && String::from_utf8(o.stderr)
                .unwrap()
                .starts_with("오류: --local-port")
    );
}

// --- additions beyond the plan text ---------------------------------------------------------------

/// F17: one binary check per command that a path error is exit 2 with nothing on stdout.
#[test]
fn path_errors_exit_2_with_nothing_on_stdout_for_every_command() {
    mcp_monitor::winutil::assert_not_elevated();
    let s = Scratch::new();
    std::fs::create_dir_all(s.join("foreign/x")).unwrap();
    let drive_root = format!("{}\\", std::env::var("SystemDrive").unwrap());
    let cases: Vec<(Vec<std::ffi::OsString>, &str)> = vec![
        (
            vec![
                "install".into(),
                "--dry-run".into(),
                "--install-dir".into(),
                drive_root.clone().into(),
                "--data-root".into(),
                s.join("d").into(),
            ],
            "--install-dir",
        ),
        (
            vec![
                "install".into(),
                "--install-dir".into(),
                s.join("i").into(),
                "--data-root".into(),
                s.join("i").join("var").into(),
            ],
            "--data-root",
        ),
        (
            vec![
                "audit-policy".into(),
                "--enable".into(),
                "--dry-run".into(),
                "--data-root".into(),
                s.join("foreign").into(),
            ],
            "--data-root",
        ),
        (
            vec![
                "audit-policy".into(),
                "--restore".into(),
                s.join("missing.csv").into(),
            ],
            "--restore",
        ),
    ];
    for (args, option) in cases {
        let o = exe().args(&args).output().unwrap();
        let err = String::from_utf8(o.stderr).unwrap();
        assert_eq!(o.status.code(), Some(2), "{args:?}: {err}");
        assert!(o.stdout.is_empty(), "{args:?}");
        assert!(
            err.starts_with(&format!("오류: {option}")),
            "{args:?}: {err}"
        );
    }
    assert!(!s.join("d").exists() && !s.join("i").exists());
}

/// Task 5 carry: a non-admin `--dry-run` over an installed (admin-only) data root exits 0 with a
/// note on stderr, and a real run still stops at require_admin with exit 1.
#[test]
fn dry_run_over_an_admin_only_data_root_exits_0_with_a_note() {
    if mcp_monitor::winutil::skip_when_elevated(
        "dry_run_over_an_admin_only_data_root_exits_0_with_a_note",
        "an administrator can read the data root, and the real run would pass require_admin",
    ) {
        return;
    }
    let s = Scratch::new();
    let root = s.join("MCP Monitor");
    std::fs::create_dir_all(root.join("data")).unwrap();
    std::fs::write(root.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
    let icacls = mcp_monitor::winutil::system_tool("icacls.exe");
    let lock = std::process::Command::new(&icacls)
        .arg(&root)
        .args([
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-18:(OI)(CI)F",
            "*S-1-5-32-544:(OI)(CI)F",
        ])
        .output()
        .unwrap();
    assert!(lock.status.success());
    // As a throw-away standard user (CI, review I1) the lock above left an explicit entry for the
    // account itself: remove it by name, so only SYSTEM and Administrators may read the folder.
    let me = mcp_monitor::winutil::current_user_sid();
    let unlock_me = std::process::Command::new(&icacls)
        .arg(&root)
        .args(["/remove:g", &format!("*{me}")])
        .output()
        .unwrap();
    assert!(unlock_me.status.success());
    let dry = exe()
        .args(["install", "--dry-run", "--install-dir"])
        .arg(s.join("i"))
        .arg("--data-root")
        .arg(&root)
        .output()
        .unwrap();
    let audit = exe()
        .args(["audit-policy", "--enable", "--dry-run", "--data-root"])
        .arg(&root)
        .output()
        .unwrap();
    let real = exe()
        .args(["install", "--install-dir"])
        .arg(s.join("i"))
        .arg("--data-root")
        .arg(&root)
        .output()
        .unwrap();
    let _ = std::process::Command::new(&icacls)
        .arg(&root)
        .args(["/reset", "/T", "/C", "/Q"])
        .output();
    for o in [&dry, &audit] {
        assert_eq!(
            o.status.code(),
            Some(0),
            "{}",
            String::from_utf8_lossy(&o.stderr)
        );
        let plan: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap();
        assert_eq!(plan["notes"].as_array().unwrap().len(), 1);
        assert!(String::from_utf8_lossy(&o.stderr).starts_with("참고: "));
    }
    assert_eq!(real.status.code(), Some(1));
    assert!(
        String::from_utf8(real.stdout.clone())
            .unwrap()
            .contains("관리자 권한으로 다시 실행하세요")
    );
    assert!(!s.join("i").exists());
}
