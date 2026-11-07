mod common;
use common::*;

#[test]
fn uninstall_without_admin_exits_1_and_changes_nothing() {
    // Carry (Task 6): on the elevated CI runner require_admin passes and the plan would really run.
    if mcp_monitor::winutil::skip_when_elevated(
        "uninstall_without_admin_exits_1_and_changes_nothing",
        "an elevated uninstall would get past require_admin",
    ) {
        return;
    }
    let s = Scratch::new();
    std::fs::create_dir_all(s.join("i")).unwrap();
    std::fs::write(s.join("i/bundle.json"), "{}").unwrap();
    std::fs::create_dir_all(s.join("d/data")).unwrap();
    std::fs::write(s.join("d/data/mcp-monitor-data-root.json"), "{}").unwrap();
    let o = exe()
        .args([
            "uninstall",
            "--remove-data",
            "--restore-audit-policy",
            "--install-dir",
        ])
        .arg(s.join("i"))
        .arg("--data-root")
        .arg(s.join("d"))
        .output()
        .unwrap();
    assert_eq!(o.status.code(), Some(1));
    assert!(
        String::from_utf8(o.stdout)
            .unwrap()
            .contains("관리자 권한으로 다시 실행하세요")
    );
    assert!(
        s.join("i/bundle.json").is_file() && s.join("d/data/mcp-monitor-data-root.json").is_file()
    );
}

#[test]
fn uninstall_dry_run_prints_the_plan() {
    let s = Scratch::new();
    let o = exe()
        .args(["uninstall", "--dry-run", "--install-dir"])
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
    let plan: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(plan["script"], "uninstall");
}

// --- additions beyond the plan text ---------------------------------------------------------------

/// Carry from Task 5: a data root inside the install folder is an argument error without
/// `--remove-data` (exit 2, nothing on stdout, the marker untouched); with it the plan removes both.
#[test]
fn a_data_root_inside_the_install_folder_needs_remove_data() {
    let s = Scratch::new();
    let data = s.join("i").join("var");
    std::fs::create_dir_all(data.join("data")).unwrap();
    std::fs::write(data.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
    std::fs::write(s.join("i/bundle.json"), "{}").unwrap();
    let dry = |extra: &[&str]| {
        exe()
            .args(["uninstall", "--dry-run", "--install-dir"])
            .arg(s.join("i"))
            .arg("--data-root")
            .arg(&data)
            .args(extra)
            .output()
            .unwrap()
    };
    let o = dry(&[]);
    assert_eq!(o.status.code(), Some(2));
    assert!(o.stdout.is_empty());
    let err = String::from_utf8(o.stderr).unwrap();
    assert!(
        err.starts_with("오류: --data-root: ") && err.contains("--remove-data로 함께 지우기"),
        "{err}"
    );
    let o = dry(&["--remove-data"]);
    assert_eq!(
        o.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&o.stderr)
    );
    let plan: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap();
    let steps = plan["steps"].as_array().unwrap();
    let ids: Vec<&str> = steps.iter().map(|x| x["id"].as_str().unwrap()).collect();
    assert_eq!(ids.first(), Some(&"require_admin"));
    assert!(ids.ends_with(&[
        "remove_install_dir",
        "remove_data",
        "remove_webview_profiles"
    ]));
    assert!(data.join("data/mcp-monitor-data-root.json").is_file());
}

/// An unsafe data root with `--remove-data` is an argument error (in any case, F04).
#[test]
fn remove_data_on_a_system_folder_is_an_argument_error() {
    let s = Scratch::new();
    let o = exe()
        .args(["uninstall", "--dry-run", "--remove-data", "--install-dir"])
        .arg(s.join("i"))
        .arg("--data-root")
        .arg(std::env::var("ProgramData").unwrap().to_lowercase())
        .output()
        .unwrap();
    assert_eq!(o.status.code(), Some(2));
    assert!(o.stdout.is_empty());
    assert!(
        String::from_utf8(o.stderr)
            .unwrap()
            .contains("--remove-data는 이 폴더를 지우지 않습니다.")
    );
}
