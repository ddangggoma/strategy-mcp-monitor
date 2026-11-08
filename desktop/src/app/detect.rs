//! What the exe finds on this PC when it starts without arguments (Y12), and where the app window
//! goes: `<I>\install.json` (ports and data root, readable by every user, Y6), the installed
//! version (Apps & features `DisplayVersion`, else the earlier PowerShell install's
//! `bundle.json`) and the decision between installing, upgrading and opening the window.

use crate::version::Version;
use serde::Deserialize;
use std::path::{Path, PathBuf};

/// `<I>\install.json` as the installer writes it (`install_info` step).
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct InstallInfo {
    pub version: String,
    pub local_port: u16,
    pub external_port: u16,
    pub data_root: PathBuf,
}

/// `<install_dir>\install.json`; `None` when it is missing, unreadable or not the expected shape.
pub fn read_install_info(install_dir: &Path) -> Option<InstallInfo> {
    let text = std::fs::read_to_string(install_dir.join("install.json")).ok()?;
    let info: InstallInfo = serde_json::from_str(&text).ok()?;
    (info.local_port != 0).then_some(info)
}

/// The installed version: the Apps & features `DisplayVersion` (`registry`), else the `version`
/// of `<install_dir>\bundle.json` (the earlier PowerShell install has no Apps & features entry).
pub fn installed_version(registry: Option<String>, install_dir: &Path) -> Option<Version> {
    registry.as_deref().and_then(Version::parse).or_else(|| {
        let text = std::fs::read_to_string(install_dir.join("bundle.json")).ok()?;
        let bundle: serde_json::Value = serde_json::from_str(&text).ok()?;
        Version::parse(bundle.get("version")?.as_str()?)
    })
}

#[derive(Debug, PartialEq)]
pub enum AutoAction {
    App,
    Install,
    Upgrade { installed: Option<Version> },
    OlderThanInstalled { installed: Version },
}

/// No service → install (also when an Apps & features entry was left behind: a repair install);
/// a service of an unknown or older version → upgrade; the same version → the window; a newer
/// install → a notice, then the installed copy's window (no downgrade).
pub fn decide(installed: Option<Version>, service_exists: bool, own: Version) -> AutoAction {
    if !service_exists {
        return AutoAction::Install;
    }
    match installed {
        None => AutoAction::Upgrade { installed: None },
        Some(v) if v < own => AutoAction::Upgrade { installed: Some(v) },
        Some(v) if v == own => AutoAction::App,
        Some(v) => AutoAction::OlderThanInstalled { installed: v },
    }
}

/// The window's home: the status board on the local channel (the same board the external
/// channel serves; its top bar there leads to the admin screen in one click).
pub fn app_url(info: &InstallInfo) -> String {
    format!("http://127.0.0.1:{}/", info.local_port)
}

/// The app window's WebView2 profile (kept between runs: the admin login stays): under the folder
/// uninstall `--remove-data` removes for every user.
pub fn app_data_dir(local_app_data: &Path) -> PathBuf {
    local_app_data.join("mcp-monitor").join("webview")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::version::Version;
    use std::fs;

    #[test]
    fn auto_mode_decisions() {
        let own = Version(1, 0, 0);
        assert_eq!(decide(None, false, own), AutoAction::Install);
        assert_eq!(
            decide(Some(Version(1, 0, 0)), false, own),
            AutoAction::Install
        ); // entry left, service gone: repair
        assert_eq!(
            decide(None, true, own),
            AutoAction::Upgrade { installed: None }
        );
        assert_eq!(
            decide(Some(Version(0, 9, 0)), true, own),
            AutoAction::Upgrade {
                installed: Some(Version(0, 9, 0))
            }
        );
        assert_eq!(decide(Some(Version(1, 0, 0)), true, own), AutoAction::App);
        assert_eq!(
            decide(Some(Version(1, 2, 0)), true, own),
            AutoAction::OlderThanInstalled {
                installed: Version(1, 2, 0)
            }
        );
        assert_eq!(
            decide(Some(Version(1, 10, 0)), true, Version(1, 9, 9)),
            AutoAction::OlderThanInstalled {
                installed: Version(1, 10, 0)
            }
        );
    }

    #[test]
    fn installed_version_falls_back_to_the_bundle_of_a_powershell_install() {
        let d = tempfile::tempdir().unwrap();
        fs::write(
            d.path().join("bundle.json"),
            r#"{"layout":"pyinstaller","version":"0.9.0"}"#,
        )
        .unwrap();
        assert_eq!(
            installed_version(Some("1.0.0".into()), d.path()),
            Some(Version(1, 0, 0))
        );
        assert_eq!(installed_version(None, d.path()), Some(Version(0, 9, 0)));
        assert_eq!(installed_version(None, &d.path().join("missing")), None);
        // an Apps & features value that is no version does not hide the bundle's
        assert_eq!(
            installed_version(Some("1.1".into()), d.path()),
            Some(Version(0, 9, 0))
        );
        fs::write(d.path().join("bundle.json"), r#"{"version":"0.9.0-rc1"}"#).unwrap();
        assert_eq!(installed_version(None, d.path()), None);
    }

    #[test]
    fn install_info_gives_the_app_url() {
        let d = tempfile::tempdir().unwrap();
        fs::write(
            d.path().join("install.json"),
            r#"{"version":"1.0.0","local_port":9700,"external_port":9701,"data_root":"D:\\MCP"}"#,
        )
        .unwrap();
        let info = read_install_info(d.path()).unwrap();
        assert_eq!(
            (app_url(&info), info.external_port),
            ("http://127.0.0.1:9700/".to_string(), 9701)
        );
        assert_eq!(info.data_root, Path::new(r"D:\MCP"));
        fs::write(d.path().join("install.json"), "{").unwrap();
        assert!(read_install_info(d.path()).is_none());
        assert_eq!(
            app_data_dir(Path::new(r"C:\Users\a\AppData\Local")),
            Path::new(r"C:\Users\a\AppData\Local\mcp-monitor\webview")
        );
    }

    #[test]
    fn install_info_needs_every_field_and_a_real_port() {
        let d = tempfile::tempdir().unwrap();
        for bad in [
            r#"{"version":"1.0.0","local_port":0,"external_port":9701,"data_root":"D:\\MCP"}"#,
            r#"{"version":"1.0.0","local_port":70000,"external_port":9701,"data_root":"D:\\MCP"}"#,
            r#"{"version":"1.0.0","external_port":9701,"data_root":"D:\\MCP"}"#,
            r#"{"version":"1.0.0","local_port":"9700","external_port":9701,"data_root":"D:\\MCP"}"#,
        ] {
            fs::write(d.path().join("install.json"), bad).unwrap();
            assert!(read_install_info(d.path()).is_none(), "{bad}");
        }
        assert!(read_install_info(&d.path().join("missing")).is_none());
    }

    #[test]
    fn the_installer_writes_what_the_app_reads() {
        // The `install_info` step of the install plan and `read_install_info` agree on the shape.
        let s = crate::install::testutil::Scratch::new();
        let h = crate::install::host::FakeHost::new();
        let a = crate::cli::InstallArgs {
            install_dir: Some(s.path().join("inst")),
            data_root: Some(s.path().join("data")),
            local_port: Some(9700),
            external_port: Some(9701),
            dry_run: true,
            ..Default::default()
        };
        let plan = crate::install::install_plan::build_install_plan(&a, &h).unwrap();
        let step = plan.steps.iter().find(|s| s.id == "install_info").unwrap();
        fs::create_dir_all(s.path().join("inst")).unwrap();
        fs::write(s.path().join("inst").join("install.json"), &step.args[1]).unwrap();
        let info = read_install_info(&s.path().join("inst")).unwrap();
        assert_eq!(
            (info.local_port, info.external_port, info.data_root),
            (9700, 9701, s.path().join("data"))
        );
    }
}
