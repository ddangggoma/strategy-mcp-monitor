//! MCP Monitor desktop executable: one GUI-subsystem exe whose first argument picks the mode.

use std::ffi::OsString;

pub mod version;

/// Entry point for `mcp-monitor.exe`; returns the process exit code. Task 4 fills in the modes.
pub fn run(args: Vec<OsString>) -> i32 {
    if args.len() == 1 && args[0] == "--version" {
        println!(
            "{}",
            version::version_line(
                version::PRODUCT,
                "000000000000",
                "none",
                cfg!(feature = "dev")
            )
        );
        return 0;
    }
    eprintln!("오류: 아직 지원하지 않는 명령입니다");
    2
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn release_builds_turn_off_tauri_dev_mode() {
        // Ruling F08: tauri's `custom-protocol` feature is on, so Tauri's own dev mode is off.
        assert!(!tauri::is_dev());
    }

    #[test]
    fn version_flag_exits_0_and_anything_else_is_an_argument_error() {
        assert_eq!(run(vec!["--version".into()]), 0);
        assert_eq!(run(vec![]), 2);
        assert_eq!(run(vec!["install".into()]), 2);
        assert_eq!(run(vec!["--version".into(), "extra".into()]), 2);
    }
}
