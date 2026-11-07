//! What `uninstall` removes and the guards around it (Plan 5's `uninstall.ps1` `(remove)` and its
//! conditions, Y20, Y21). A link (junction or symbolic link) is never followed: only the link
//! itself is removed.

use crate::install::paths::{
    Env, Volumes, attributes, data_root_marker, is_directory, is_inside, is_reparse, same_path,
    unsafe_root_reason,
};
use crate::install::registry::Registry;
use crate::install::stage::EXE_NAME;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

/// The per-user autostart value (Y20) below `HKCU` / `HKU\<SID>`.
pub const RUN_KEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Run";
pub const RUN_VALUE: &str = "MCPMonitor";

/// How long a removal keeps trying while another process still holds a file (F26: a WebView2
/// process of another session that is still exiting).
const RETRY_FOR: Duration = Duration::from_secs(10);

/// `install_dir_is_bundle`: an install folder (`bundle.json`) that is no drive root, system
/// folder or path through a link (Plan 5 I3).
pub fn install_dir_is_bundle(dir: &Path, env: &Env, vols: &dyn Volumes) -> bool {
    unsafe_root_reason(&dir.display().to_string(), env, vols).is_none()
        && dir.join("bundle.json").is_file()
}

/// `data_root_is_ours`: a data root with our marker (`Test-DataRootMarker`) that is safe to
/// delete whole.
pub fn data_root_is_ours(root: &Path, env: &Env, vols: &dyn Volumes) -> bool {
    unsafe_root_reason(&root.display().to_string(), env, vols).is_none() && data_root_marker(root)
}

/// The error kinds that go away once another process lets go of a file: access denied (a delete
/// pending), sharing and lock violations, a folder not yet empty.
fn busy(e: &io::Error) -> bool {
    matches!(e.raw_os_error(), Some(5 | 32 | 33 | 145))
}

/// `f` again every 200 ms while it fails with [`busy`], for at most `within`.
fn retrying(within: Duration, mut f: impl FnMut() -> io::Result<()>) -> io::Result<()> {
    let deadline = Instant::now() + within;
    loop {
        match f() {
            Err(e) if busy(&e) && Instant::now() < deadline => {
                std::thread::sleep(Duration::from_millis(200))
            }
            r => return r,
        }
    }
}

/// Removes `p` if it exists: a file, a folder with everything in it (links inside are removed,
/// not followed), or only the link when `p` itself is one.
pub fn remove_path(p: &Path) -> Result<(), String> {
    remove_path_within(p, RETRY_FOR)
}

fn remove_path_within(p: &Path, within: Duration) -> Result<(), String> {
    let fail = |e: io::Error| format!("{} 을(를) 지우지 못했습니다: {e}", p.display());
    let a = match attributes(p) {
        Ok(a) => a,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(e) => return Err(fail(e)),
    };
    retrying(within, || {
        let r = match (is_reparse(a), is_directory(a)) {
            (true, true) => fs::remove_dir(p),
            (false, true) => fs::remove_dir_all(p),
            (_, false) => fs::remove_file(p),
        };
        match r {
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
            r => r,
        }
    })
    .map_err(fail)
}

/// `<dir>\mcp-monitor.exe.uninstalled`, or `-2`, `-3` … when an earlier uninstall left one behind
/// before a restart.
fn free_name(dir: &Path) -> PathBuf {
    let base = format!("{EXE_NAME}.uninstalled");
    (1..)
        .map(|n| match n {
            1 => dir.join(&base),
            n => dir.join(format!("{base}-{n}")),
        })
        .find(|p| fs::symlink_metadata(p).is_err())
        .expect("an unused name exists")
}

/// Removes the install folder `dir` (Y21). When this program (`self_exe`) runs from inside it, its
/// image cannot be deleted: it is renamed to `mcp-monitor.exe.uninstalled` (moved to the top of
/// `dir`), everything else is removed, and that file and then `dir` are handed to `schedule`
/// (`MoveFileExW(…, MOVEFILE_DELAY_UNTIL_REBOOT)`). Otherwise `dir` is removed whole.
pub fn remove_install_dir(
    dir: &Path,
    self_exe: &Path,
    schedule: &mut dyn FnMut(&Path),
) -> Result<(), String> {
    if !is_inside(self_exe, dir) {
        return remove_path(dir);
    }
    let kept = free_name(dir);
    fs::rename(self_exe, &kept).map_err(|e| {
        format!(
            "실행 중인 {} 을(를) {} 로 바꾸지 못했습니다: {e}",
            self_exe.display(),
            kept.display()
        )
    })?;
    let entries =
        fs::read_dir(dir).map_err(|e| format!("{} 을(를) 읽지 못했습니다: {e}", dir.display()))?;
    for entry in entries {
        let p = entry
            .map_err(|e| format!("{} 을(를) 읽지 못했습니다: {e}", dir.display()))?
            .path();
        if !same_path(&p, &kept) {
            remove_path(&p)?;
        }
    }
    schedule(&kept);
    schedule(dir);
    Ok(())
}

/// A real folder, not a link to one.
fn real_dir(p: &Path) -> bool {
    attributes(p).is_ok_and(|a| is_directory(a) && !is_reparse(a))
}

/// `remove_webview_profiles`: removes `<Users>\*\AppData\Local\mcp-monitor` of every user (the
/// notice window's Edge and WebView2 data and the app window's profile) and returns how many
/// were removed. Only that pattern (`*` exactly one level, the last three parts fixed); a user,
/// `AppData` or `Local` folder that is a link is not walked into, a profile folder that is a link
/// loses only the link. Every user is tried; the failures are reported together.
pub fn remove_glob(pattern: &Path) -> Result<u32, String> {
    remove_glob_within(pattern, RETRY_FOR)
}

pub(crate) fn remove_glob_within(pattern: &Path, within: Duration) -> Result<u32, String> {
    let named = |p: Option<&Path>, want: &str| {
        p.and_then(Path::file_name)
            .is_some_and(|n| n.to_string_lossy().eq_ignore_ascii_case(want))
    };
    let local = pattern.parent();
    let appdata = local.and_then(Path::parent);
    let star = appdata.and_then(Path::parent);
    let users = star.and_then(Path::parent);
    let fixed = named(Some(pattern), "mcp-monitor")
        && named(local, "Local")
        && named(appdata, "AppData")
        && star.and_then(Path::file_name).is_some_and(|n| n == "*")
        && users.is_some_and(|u| {
            u.is_absolute() && u.parent().is_some() && !u.to_string_lossy().contains('*')
        });
    let (true, Some(users)) = (fixed, users) else {
        return Err(format!(
            "{} 은(는) <사용자 폴더>\\*\\AppData\\Local\\mcp-monitor 형태가 아닙니다",
            pattern.display()
        ));
    };
    let entries = match fs::read_dir(users) {
        Ok(e) => e,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(0),
        Err(e) => return Err(format!("{} 을(를) 읽지 못했습니다: {e}", users.display())),
    };
    let (mut removed, mut failed) = (0u32, Vec::new());
    for entry in entries {
        let user = match entry {
            Ok(e) => e.path(),
            Err(e) => {
                failed.push(format!("{} 을(를) 읽지 못했습니다: {e}", users.display()));
                continue;
            }
        };
        let local = user.join("AppData").join("Local");
        if !real_dir(&user) || !real_dir(&user.join("AppData")) || !real_dir(&local) {
            continue;
        }
        let profile = local.join("mcp-monitor");
        match attributes(&profile) {
            Ok(a) if is_directory(a) => match remove_path_within(&profile, within) {
                Ok(()) => removed += 1,
                Err(e) => failed.push(e),
            },
            Ok(_) => {}
            Err(e) if e.kind() == io::ErrorKind::NotFound => {}
            Err(e) => failed.push(format!(
                "{} 을(를) 확인하지 못했습니다: {e}",
                profile.display()
            )),
        }
    }
    if failed.is_empty() {
        Ok(removed)
    } else {
        Err(failed.join("; "))
    }
}

/// The program a `Run` value starts: the text inside the first quotes, or, unquoted, the whole
/// value (Windows tries every prefix up to a space, so it is ours when the value begins inside
/// the install folder).
pub fn run_program(data: &str) -> &str {
    let t = data.trim_start();
    match t.strip_prefix('"') {
        Some(rest) => rest.split('"').next().unwrap_or_default(),
        None => t.trim_end(),
    }
}

/// The SIDs of `values` (`(SID, Run value data)`) whose program lies inside `install_dir`
/// (ignoring case, F04).
pub fn select_run_values(values: &[(String, String)], install_dir: &Path) -> Vec<String> {
    values
        .iter()
        .filter(|(_, data)| is_inside(Path::new(run_program(data)), install_dir))
        .map(|(sid, _)| sid.clone())
        .collect()
}

/// A loaded user hive (`HKU\S-1-5-21-…`), not its `_Classes` companion.
fn is_user_hive(name: &str) -> bool {
    name.get(..9)
        .is_some_and(|p| p.eq_ignore_ascii_case("S-1-5-21-"))
        && !name.to_ascii_lowercase().ends_with("_classes")
}

/// `(run-values-remove)`: deletes `Run\MCPMonitor` of every loaded user hive where it starts our
/// program from `install_dir`, and returns those SIDs. Users who are not logged on keep theirs
/// (harmless once the program is gone, E2 / Y20).
pub fn remove_run_values(
    reg: &mut dyn Registry,
    install_dir: &Path,
) -> Result<Vec<String>, String> {
    let values: Vec<(String, String)> = reg
        .subkeys("HKU")
        .into_iter()
        .filter(|sid| is_user_hive(sid))
        .filter_map(|sid| {
            let data = reg.string(&format!(r"HKU\{sid}\{RUN_KEY}"), RUN_VALUE)?;
            Some((sid, data))
        })
        .collect();
    let ours = select_run_values(&values, install_dir);
    for sid in &ours {
        reg.delete_value(&format!(r"HKU\{sid}\{RUN_KEY}"), RUN_VALUE)?;
    }
    Ok(ours)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::paths::{Env, SystemVolumes};
    use crate::install::testutil::*;
    use std::fs;

    #[test]
    fn only_a_marked_data_root_and_a_bundle_install_dir_are_removed() {
        let s = Scratch::new();
        let (bare, marked, inst) = (
            s.path().join("bare"),
            s.path().join("marked"),
            s.path().join("i"),
        );
        for d in [&bare, &marked, &inst] {
            fs::create_dir_all(d.join("data")).unwrap();
        }
        fs::write(marked.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        fs::write(inst.join("bundle.json"), "{}").unwrap();
        let (e, v) = (Env::from_process(), SystemVolumes);
        assert!(!data_root_is_ours(&bare, &e, &v) && data_root_is_ours(&marked, &e, &v));
        assert!(install_dir_is_bundle(&inst, &e, &v) && !install_dir_is_bundle(&bare, &e, &v));
        let drive = PathBuf::from(format!("{}\\", std::env::var("SystemDrive").unwrap()));
        assert!(!data_root_is_ours(&drive, &e, &v) && !install_dir_is_bundle(&drive, &e, &v));
    }

    #[test]
    fn remove_install_dir_keeps_the_running_exe_for_reboot() {
        let s = Scratch::new();
        let inst = s.path().join("i");
        fs::create_dir_all(inst.join("bin/monitor")).unwrap();
        fs::write(inst.join("bin/monitor/mcp-monitor-server.exe"), b"x").unwrap();
        fs::write(inst.join("mcp-monitor.exe"), b"MZ").unwrap();
        fs::write(inst.join("bundle.json"), "{}").unwrap();
        let mut scheduled = Vec::new();
        remove_install_dir(&inst, &inst.join("mcp-monitor.exe"), &mut |p: &Path| {
            scheduled.push(p.to_path_buf())
        })
        .unwrap();
        let left: Vec<String> = fs::read_dir(&inst)
            .unwrap()
            .map(|e| e.unwrap().file_name().into_string().unwrap())
            .collect();
        assert_eq!(left, ["mcp-monitor.exe.uninstalled"]);
        assert_eq!(
            scheduled,
            [inst.join("mcp-monitor.exe.uninstalled"), inst.clone()]
        );
        let other = s.path().join("j");
        fs::create_dir_all(&other).unwrap();
        fs::write(other.join("bundle.json"), "{}").unwrap();
        remove_install_dir(&other, &s.path().join("elsewhere.exe"), &mut |_: &Path| {
            panic!("nothing to schedule")
        })
        .unwrap();
        assert!(!other.exists());
    }

    #[test]
    fn webview_profiles_are_removed_and_nothing_else() {
        let s = Scratch::new();
        let users = s.path().join("Users");
        for (user, sub) in [
            ("alice", "notice-edge"),
            ("alice", "webview"),
            ("bob", "notice-webview"),
        ] {
            fs::create_dir_all(users.join(user).join("AppData/Local/mcp-monitor").join(sub))
                .unwrap();
        }
        fs::create_dir_all(users.join("bob/AppData/Local/other")).unwrap();
        assert_eq!(
            remove_glob(
                &users
                    .join("*")
                    .join("AppData")
                    .join("Local")
                    .join("mcp-monitor")
            )
            .unwrap(),
            2
        );
        assert!(
            !users.join("alice/AppData/Local/mcp-monitor").exists()
                && !users.join("bob/AppData/Local/mcp-monitor").exists()
        );
        assert!(users.join("bob/AppData/Local/other").is_dir());
        assert!(remove_glob(&users.join("*").join("AppData")).is_err()); // only the fixed profile pattern
    }

    #[test]
    fn run_values_only_ours() {
        let values = [
            (
                "S-1-5-21-1-1001".to_string(),
                r#""C:\Program Files\MCP Monitor\mcp-monitor.exe" app --background"#.to_string(),
            ),
            (
                "S-1-5-21-1-1002".to_string(),
                r#""C:\Program Files\Other\mcp-monitor.exe" app --background"#.to_string(),
            ),
            (
                "S-1-5-21-1-1003".to_string(),
                r"c:\program files\mcp monitor\mcp-monitor.exe app --background".to_string(),
            ),
        ];
        assert_eq!(
            select_run_values(&values, Path::new(r"C:\Program Files\MCP Monitor")),
            ["S-1-5-21-1-1001", "S-1-5-21-1-1003"]
        );
    }

    // --- additions beyond the plan text -----------------------------------------------------------

    /// A link in place of a profile folder: only the link goes, never what it points at. A user
    /// entry that is itself a link (`Default User`, `All Users`) is not walked into at all.
    #[test]
    fn remove_glob_never_follows_links() {
        let s = Scratch::new();
        let users = s.path().join("Users");
        let elsewhere = s.path().join("elsewhere");
        fs::create_dir_all(users.join("carol/AppData/Local")).unwrap();
        junction(&users.join("carol/AppData/Local/mcp-monitor"), &elsewhere);
        fs::write(elsewhere.join("keep.txt"), "x").unwrap();
        let hidden = s.path().join("other-users").join("eve");
        fs::create_dir_all(hidden.join("AppData/Local/mcp-monitor/webview")).unwrap();
        junction(&users.join("Default User"), &hidden);
        let pattern = users
            .join("*")
            .join("AppData")
            .join("Local")
            .join("mcp-monitor");
        assert_eq!(remove_glob(&pattern).unwrap(), 1);
        assert!(!users.join("carol/AppData/Local/mcp-monitor").exists());
        assert!(
            elsewhere.join("keep.txt").is_file(),
            "the link's target stays"
        );
        assert!(
            hidden.join("AppData/Local/mcp-monitor/webview").is_dir(),
            "a linked user folder is not walked into"
        );
        // Nothing (left) to remove, and a missing Users folder: 0.
        assert_eq!(remove_glob(&pattern).unwrap(), 0);
        assert_eq!(
            remove_glob(
                &s.path()
                    .join("missing")
                    .join("*")
                    .join("AppData")
                    .join("Local")
                    .join("mcp-monitor")
            )
            .unwrap(),
            0
        );
    }

    #[test]
    fn remove_glob_takes_only_the_fixed_profile_pattern() {
        let base = Path::new(r"C:\Users");
        for bad in [
            base.join("*").join("AppData").join("Local").join("other"),
            base.join("alice")
                .join("AppData")
                .join("Local")
                .join("mcp-monitor"),
            base.join("a*")
                .join("AppData")
                .join("Local")
                .join("mcp-monitor"),
            base.join("*")
                .join("*")
                .join("AppData")
                .join("Local")
                .join("mcp-monitor"),
            base.join("*")
                .join("AppData")
                .join("Roaming")
                .join("mcp-monitor"),
            PathBuf::from(r"*\AppData\Local\mcp-monitor"),
            PathBuf::from(r"Users\*\AppData\Local\mcp-monitor"),
        ] {
            assert!(remove_glob(&bad).is_err(), "{}", bad.display());
        }
    }

    /// F26: a profile still held by an exiting WebView2 process of another session: tried again
    /// for a while, then removed once the handle is gone; still held at the end: an error.
    #[test]
    fn a_profile_held_open_for_a_moment_is_removed_after_a_retry() {
        use std::os::windows::fs::OpenOptionsExt;
        let s = Scratch::new();
        let users = s.path().join("Users");
        let file = users.join("alice/AppData/Local/mcp-monitor/webview/lock");
        fs::create_dir_all(file.parent().unwrap()).unwrap();
        fs::write(&file, "x").unwrap();
        let pattern = users
            .join("*")
            .join("AppData")
            .join("Local")
            .join("mcp-monitor");
        let held = fs::OpenOptions::new()
            .read(true)
            .share_mode(0)
            .open(&file)
            .unwrap();
        let e = remove_glob_within(&pattern, std::time::Duration::from_millis(300)).unwrap_err();
        assert!(e.contains("mcp-monitor"), "{e}");
        let release = std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_millis(400));
            drop(held);
        });
        assert_eq!(
            remove_glob_within(&pattern, std::time::Duration::from_secs(10)).unwrap(),
            1
        );
        release.join().unwrap();
        assert!(!users.join("alice/AppData/Local/mcp-monitor").exists());
    }

    /// A leftover `.uninstalled` from an uninstall before the last restart: the next name is used.
    /// A link inside the install folder goes without its target; a self exe written in another
    /// case is still the one inside (F04).
    #[test]
    fn remove_install_dir_picks_a_free_name_and_does_not_follow_links() {
        let s = Scratch::new();
        let inst = s.path().join("MCP Monitor");
        fs::create_dir_all(&inst).unwrap();
        fs::write(inst.join("bundle.json"), "{}").unwrap();
        fs::write(inst.join("mcp-monitor.exe"), b"MZ").unwrap();
        fs::write(inst.join("mcp-monitor.exe.uninstalled"), b"old").unwrap();
        let target = s.path().join("target");
        junction(&inst.join("linked"), &target);
        fs::write(target.join("keep.txt"), "x").unwrap();
        let mut scheduled = Vec::new();
        let exe = PathBuf::from(swap_case(&inst.join("mcp-monitor.exe")));
        remove_install_dir(&inst, &exe, &mut |p: &Path| scheduled.push(p.to_path_buf())).unwrap();
        let left: Vec<String> = fs::read_dir(&inst)
            .unwrap()
            .map(|e| e.unwrap().file_name().into_string().unwrap())
            .collect();
        assert_eq!(left, ["mcp-monitor.exe.uninstalled-2"]);
        assert_eq!(
            fs::read(inst.join("mcp-monitor.exe.uninstalled-2")).unwrap(),
            b"MZ"
        );
        assert_eq!(
            scheduled,
            [inst.join("mcp-monitor.exe.uninstalled-2"), inst.clone()]
        );
        assert!(target.join("keep.txt").is_file());
    }

    #[test]
    fn run_values_are_removed_only_from_user_hives_and_only_ours() {
        use crate::install::registry::{FakeRegistry, RegValue, Registry};
        let inst = Path::new(r"C:\Program Files\MCP Monitor");
        let ours = r#""C:\Program Files\MCP Monitor\mcp-monitor.exe" app --background"#;
        let mut reg = FakeRegistry::default();
        for (sid, data) in [
            ("S-1-5-21-9-1001", ours),
            ("S-1-5-21-9-1002", r#""D:\Other\mcp-monitor.exe" app"#),
            ("S-1-5-21-9-1001_Classes", ours),
            ("S-1-5-18", ours),
            (".DEFAULT", ours),
        ] {
            reg.set_values(
                &format!(r"HKU\{sid}\{RUN_KEY}"),
                &[
                    (RUN_VALUE.into(), RegValue::Sz(data.into())),
                    ("Other".into(), RegValue::Sz(ours.into())),
                ],
            )
            .unwrap();
        }
        reg.set_values(r"HKU\S-1-5-21-9-1003\Software", &[])
            .unwrap();
        assert_eq!(
            remove_run_values(&mut reg, inst).unwrap(),
            ["S-1-5-21-9-1001"]
        );
        let value = |sid: &str, name: &str| reg.string(&format!(r"HKU\{sid}\{RUN_KEY}"), name);
        assert_eq!(value("S-1-5-21-9-1001", RUN_VALUE), None);
        assert_eq!(
            value("S-1-5-21-9-1001", "Other").as_deref(),
            Some(ours),
            "only our value goes"
        );
        for kept in [
            "S-1-5-21-9-1002",
            "S-1-5-21-9-1001_Classes",
            "S-1-5-18",
            ".DEFAULT",
        ] {
            assert!(value(kept, RUN_VALUE).is_some(), "{kept}");
        }
        assert!(remove_run_values(&mut reg, inst).unwrap().is_empty());
    }

    #[test]
    fn run_value_commands_are_read_like_windows_starts_them() {
        let inst = Path::new(r"C:\Program Files\MCP Monitor");
        assert_eq!(run_program(r#""C:\a b\x.exe" app"#), r"C:\a b\x.exe");
        assert_eq!(run_program(r#"  "C:\a b\x.exe"#), r"C:\a b\x.exe");
        assert_eq!(
            run_program(r"C:\x.exe --background"),
            r"C:\x.exe --background"
        );
        let pick = |data: &str| select_run_values(&[("S".into(), data.into())], inst);
        assert!(pick(r#""C:\Program Files\MCP Monitor\bin\x.exe""#).len() == 1);
        for foreign in [
            r#""C:\Program Files\MCP Monitor2\mcp-monitor.exe" app"#,
            r#""C:\Other\x.exe" "C:\Program Files\MCP Monitor\mcp-monitor.exe""#,
            r"C:\Other\x.exe C:\Program Files\MCP Monitor\mcp-monitor.exe",
            r#""C:\Program Files\MCP Monitor""#,
            "",
        ] {
            assert!(pick(foreign).is_empty(), "{foreign}");
        }
    }

    #[test]
    fn remove_path_removes_files_folders_and_links_only() {
        let s = Scratch::new();
        let (file, dir, target) = (
            s.path().join("a.lnk"),
            s.path().join("d"),
            s.path().join("t"),
        );
        fs::write(&file, "x").unwrap();
        fs::create_dir_all(dir.join("logs")).unwrap();
        fs::write(dir.join("logs/x.log"), "x").unwrap();
        junction(&s.path().join("link"), &target);
        fs::write(target.join("keep.txt"), "x").unwrap();
        for p in [
            &file,
            &dir,
            &s.path().join("link"),
            &s.path().join("missing"),
        ] {
            remove_path(p).unwrap();
            assert!(fs::symlink_metadata(p).is_err(), "{}", p.display());
        }
        assert!(target.join("keep.txt").is_file());
    }
}
