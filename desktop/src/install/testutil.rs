//! Test helpers for the installer modules: a scratch folder under
//! `%LOCALAPPDATA%\mcp-monitor-install-tests`, icacls, junctions and SDDL. Never used elevated.

use crate::install::acl::{ADMINISTRATORS, AUTHENTICATED_USERS, SYSTEM, sddl_of};
use crate::winutil::{assert_not_elevated, current_user_sid, system_tool};
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::Command;

/// `%LOCALAPPDATA%\mcp-monitor-install-tests\<random>`: its parents are folders only this account,
/// SYSTEM and Administrators can change. Reset and deleted on drop.
pub struct Scratch(PathBuf);

impl Scratch {
    #[allow(clippy::new_without_default)]
    pub fn new() -> Scratch {
        // Tests that use a scratch folder change files and ACLs: never from an elevated shell.
        assert_not_elevated();
        let mut b = [0u8; 6];
        getrandom::fill(&mut b).unwrap();
        let p = PathBuf::from(std::env::var("LOCALAPPDATA").unwrap())
            .join("mcp-monitor-install-tests")
            .join(hex::encode(b));
        std::fs::create_dir_all(&p).unwrap();
        Scratch(p)
    }
    pub fn path(&self) -> &Path {
        &self.0
    }
    pub fn join(&self, p: &str) -> PathBuf {
        self.0.join(p)
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        // A test may have locked an item or taken a right away: reset everything to inherited first.
        let _ = Command::new(system_tool("icacls.exe"))
            .arg(&self.0)
            .args(["/reset", "/T", "/C", "/Q"])
            .output();
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

/// Runs `icacls <path> <args>` and fails the test if it fails.
pub fn icacls(path: &Path, args: &[&str]) {
    let out = Command::new(system_tool("icacls.exe"))
        .arg(path)
        .args(args)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "icacls {path:?} {args:?}: {}{}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
}

/// An installed data root as a standard user sees it: only SYSTEM and Administrators on `path`
/// (protected, no inherited entries). This account's own entry is removed by name too: as a
/// throw-away standard user on the CI runner, `/inheritance:r /grant:r` alone left an explicit
/// full-access entry for the account (review I1), and the folder stayed readable.
pub fn lock_to_admins(path: &Path) {
    icacls(
        path,
        &[
            "/inheritance:r",
            "/grant:r",
            &format!("*{SYSTEM}:(OI)(CI)F"),
            &format!("*{ADMINISTRATORS}:(OI)(CI)F"),
        ],
    );
    icacls(path, &["/remove:g", &format!("*{}", me())]);
    // The owner stays this account (O:…); the DACL must not name it.
    let sddl = sddl(path);
    let dacl = sddl.split_once("D:").map_or("", |(_, d)| d);
    assert!(!dacl.contains(&me()), "{sddl}");
}

/// `icacls <path> /grant *S-1-5-11:<rights>` (Authenticated Users).
pub fn grant(path: &Path, rights: &str) {
    icacls(
        path,
        &["/grant", &format!("*{AUTHENTICATED_USERS}:{rights}")],
    );
}

/// A junction `link` → `target` (made if missing); no admin needed, unlike a symbolic link.
pub fn junction(link: &Path, target: &Path) {
    std::fs::create_dir_all(target).unwrap();
    let out = Command::new(system_tool("cmd.exe"))
        .raw_arg(format!(
            "/d /c mklink /J \"{}\" \"{}\"",
            link.display(),
            target.display()
        ))
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "mklink /J {link:?}: {}",
        String::from_utf8_lossy(&out.stdout)
    );
}

/// The owner and DACL of `path` as SDDL.
pub fn sddl(path: &Path) -> String {
    sddl_of(path).unwrap()
}

/// This account's SID; it stands in for Administrators as the owner in tests (Y18).
pub fn me() -> String {
    current_user_sid()
}

/// SYSTEM, Administrators and this account.
pub fn owners() -> Vec<String> {
    vec![SYSTEM.to_string(), ADMINISTRATORS.to_string(), me()]
}

/// `root` and everything below it, without entering junctions or links.
pub fn walk_all(root: &Path) -> Vec<PathBuf> {
    walkdir::WalkDir::new(root)
        .follow_links(false)
        .into_iter()
        .map(|e| e.unwrap().into_path())
        .collect()
}

/// `path` with every letter in the other case (`C:\Users` → `c:\uSERS`), for the case-folding tests (F04).
pub fn swap_case(path: &Path) -> String {
    path.display()
        .to_string()
        .chars()
        .map(|c| {
            if c.is_uppercase() {
                c.to_lowercase().next().unwrap()
            } else {
                c.to_uppercase().next().unwrap()
            }
        })
        .collect()
}
