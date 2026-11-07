//! "Start the tray when I sign in" (Y20): the current user's `Run` value `MCPMonitor` =
//! `"<I>\mcp-monitor.exe" app --background`. Only the app mode of that user writes it (the tray's
//! check item and `autostart on|off`); uninstall removes it from every loaded user hive.

use crate::install::registry::{RegValue, Registry};
use std::path::Path;

pub const RUN_KEY: &str = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run";
pub const RUN_VALUE: &str = "MCPMonitor";

/// The command the `Run` value starts: the installed exe in the tray only.
pub fn run_value(install_dir: &Path) -> String {
    format!(
        "\"{}\" app --background",
        install_dir.join("mcp-monitor.exe").display()
    )
}

/// Writes (`on`) or removes (`off`) the `Run` value. Removing a value that is not there is fine.
pub fn set_autostart(reg: &mut dyn Registry, install_dir: &Path, on: bool) -> Result<(), String> {
    if on {
        reg.set_values(
            RUN_KEY,
            &[(RUN_VALUE.to_string(), RegValue::Sz(run_value(install_dir)))],
        )
    } else {
        reg.delete_value(RUN_KEY, RUN_VALUE)
    }
}

/// True only when the value is exactly [`run_value`] of `install_dir` (a value another install or
/// a hand edit left reads as off, and turning it on writes ours).
pub fn autostart_enabled(reg: &dyn Registry, install_dir: &Path) -> bool {
    reg.string(RUN_KEY, RUN_VALUE).as_deref() == Some(run_value(install_dir).as_str())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::registry::FakeRegistry;

    #[test]
    fn autostart_writes_and_removes_the_run_value() {
        let dir = Path::new(r"C:\Program Files\MCP Monitor");
        assert_eq!(
            run_value(dir),
            r#""C:\Program Files\MCP Monitor\mcp-monitor.exe" app --background"#
        );
        let mut r = FakeRegistry::default();
        assert!(!autostart_enabled(&r, dir));
        set_autostart(&mut r, dir, true).unwrap();
        assert!(
            autostart_enabled(&r, dir)
                && r.string(RUN_KEY, RUN_VALUE).as_deref() == Some(run_value(dir).as_str())
        );
        assert!(!autostart_enabled(&r, Path::new(r"D:\Other")));
        set_autostart(&mut r, dir, false).unwrap();
        assert!(!autostart_enabled(&r, dir) && r.string(RUN_KEY, RUN_VALUE).is_none());
        // off twice is still fine, and nothing else in the key is touched
        r.set_values(RUN_KEY, &[("Other".into(), RegValue::Sz("x.exe".into()))])
            .unwrap();
        set_autostart(&mut r, dir, false).unwrap();
        assert_eq!(r.string(RUN_KEY, "Other").as_deref(), Some("x.exe"));
    }

    #[test]
    fn uninstall_finds_the_value_autostart_writes() {
        // Uninstall removes `HKU\<SID>\<remove::RUN_KEY>\<remove::RUN_VALUE>` when its program
        // lies inside the install folder: the same key, value name and program as written here.
        use crate::install::remove::{RUN_KEY as HKU_RUN_KEY, RUN_VALUE as HKU_RUN_VALUE};
        assert_eq!(RUN_KEY, format!(r"HKCU\{HKU_RUN_KEY}"));
        assert_eq!(RUN_VALUE, HKU_RUN_VALUE);
        let dir = Path::new(r"C:\Program Files\MCP Monitor");
        let values = [("S-1-5-21-1".to_string(), run_value(dir))];
        assert_eq!(
            crate::install::remove::select_run_values(&values, dir),
            ["S-1-5-21-1"]
        );
    }
}
