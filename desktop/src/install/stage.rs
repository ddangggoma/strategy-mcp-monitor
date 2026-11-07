//! The install folder's new contents and the folder swap (Y14, Y15): the embedded payload is
//! extracted into `<I>.staging` (hash-checked, marked as ours) while the service still runs; after
//! the service and the apps stopped, `<I>` moves aside to `<I>.old` and the staging folder takes
//! its place, rolled back when the move fails or the new tree is not admin-only. `<I>.old` goes
//! once the new service answers.

use crate::install::acl::install_tree_problem;
use crate::install::paths::is_inside;
use crate::payload::{self, STAGING_MARKER, extract, verify_archive};
use crate::payload_pack::Manifest;
use sha2::{Digest, Sha256};
use std::fs;
use std::io::{self, Read};
use std::path::Path;
use windows::Win32::Storage::FileSystem::{MOVEFILE_WRITE_THROUGH, MoveFileExW};
use windows::core::HSTRING;

/// The name the installer gives its own copy in the install folder (Y6).
pub const EXE_NAME: &str = "mcp-monitor.exe";

/// What [`stage`] extracts: the archive, its expected SHA-256, the manifest and the build kind.
pub struct PayloadSource {
    pub archive: Vec<u8>,
    pub sha256: String,
    pub manifest: Manifest,
    /// `release`, or `fixture` (built without `MCPMON_PAYLOAD_DIR`), which is never installed.
    pub kind: String,
}

impl PayloadSource {
    /// The payload embedded in this exe.
    pub fn embedded() -> PayloadSource {
        PayloadSource {
            archive: payload::ARCHIVE.to_vec(),
            sha256: payload::ARCHIVE_SHA256.trim().to_string(),
            manifest: payload::manifest(),
            kind: payload::KIND.trim().to_string(),
        }
    }
}

/// Lower-case hex SHA-256 of a file, read in chunks.
fn file_sha256(path: &Path) -> io::Result<String> {
    let mut file = fs::File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buf = vec![0u8; 256 * 1024];
    loop {
        let n = file.read(&mut buf)?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    Ok(hex::encode(hasher.finalize()))
}

/// Ruling F06: the installer must not run from the install folder (or its `.staging`/`.old`
/// neighbours). Its own image would keep `<I>` from being moved aside, so every repair from the
/// installed copy would fail at the swap. `None`: `self_exe` is elsewhere.
pub fn running_inside_problem(
    self_exe: &Path,
    install_dir: &Path,
    version: &str,
) -> Option<String> {
    let inst = install_dir.display().to_string();
    let inside = [
        inst.clone(),
        format!("{inst}.staging"),
        format!("{inst}.old"),
    ]
    .iter()
    .any(|dir| is_inside(self_exe, Path::new(dir)));
    inside.then(|| {
        format!(
            "{} 은(는) 설치 폴더 안의 실행 파일이라 설치 폴더를 바꿀 수 없습니다. 다운로드한 mcp-monitor-{version}.exe로 실행하세요.",
            self_exe.display()
        )
    })
}

/// Extracts the payload into the new folder `staging` and copies this exe (`self_exe`) next to
/// it as `mcp-monitor.exe`. Returns the bytes written. A fixture payload is refused before
/// anything is made; an existing `staging` is removed only when it holds our marker.
pub fn stage(staging: &Path, src: &PayloadSource, self_exe: &Path) -> Result<u64, String> {
    if src.kind != "release" {
        return Err("개발용(fixture) payload로는 설치할 수 없습니다. install\\build-desktop.ps1로 만든 실행 파일을 쓰세요.".into());
    }
    verify_archive(&src.archive, &src.sha256).map_err(|e| e.to_string())?;
    let shown = staging.display();
    if fs::symlink_metadata(staging).is_ok() {
        if !staging.join(STAGING_MARKER).is_file() {
            return Err(format!(
                "{shown} 이(가) 이미 있고 설치기가 만든 폴더가 아닙니다"
            ));
        }
        // An earlier, unfinished staging of ours.
        fs::remove_dir_all(staging)
            .map_err(|e| format!("{shown} 을(를) 지우지 못했습니다: {e}"))?;
    }
    let written = extract(&src.archive, &src.manifest, staging).map_err(|e| e.to_string())?;
    let copy = staging.join(EXE_NAME);
    let copied = fs::copy(self_exe, &copy).map_err(|e| {
        format!(
            "{} 을(를) {} 로 복사하지 못했습니다: {e}",
            self_exe.display(),
            copy.display()
        )
    })?;
    let hash = |p: &Path| {
        file_sha256(p).map_err(|e| format!("{} 을(를) 읽지 못했습니다: {e}", p.display()))
    };
    if hash(self_exe)? != hash(&copy)? {
        return Err(format!(
            "{} 의 해시가 원본({})과 다릅니다",
            copy.display(),
            self_exe.display()
        ));
    }
    Ok(written + copied)
}

/// Folder renames, replaceable in tests (a sharing violation half-way).
pub trait FsOps {
    fn rename(&self, from: &Path, to: &Path) -> io::Result<()>;
}

/// `MoveFileExW(from, to, MOVEFILE_WRITE_THROUGH)`: a folder rename on the same volume, flushed
/// before it returns.
pub struct StdFs;

impl FsOps for StdFs {
    fn rename(&self, from: &Path, to: &Path) -> io::Result<()> {
        // SAFETY: both HSTRINGs are NUL-terminated and outlive the call.
        unsafe {
            MoveFileExW(
                &HSTRING::from(from),
                &HSTRING::from(to),
                MOVEFILE_WRITE_THROUGH,
            )
        }
        .map_err(|e| io::Error::from_raw_os_error(e.code().0 & 0xFFFF))
    }
}

fn exists(p: &Path) -> bool {
    fs::symlink_metadata(p).is_ok()
}

fn has_bundle(dir: &Path) -> bool {
    dir.join("bundle.json").is_file()
}

/// Puts `staging` in place of `install_dir`; an earlier install moves to `old`. Rolls back (the
/// earlier install back in place, the new tree back to `staging` with its marker) when the move
/// fails or the new tree fails [`install_tree_problem`] for `owners`.
pub fn swap(
    staging: &Path,
    install_dir: &Path,
    old: &Path,
    fs_ops: &dyn FsOps,
    owners: &[String],
) -> Result<(), String> {
    let (s, i, o) = (staging.display(), install_dir.display(), old.display());
    let marker_path = staging.join(STAGING_MARKER);
    let marker = fs::read(&marker_path)
        .map_err(|_| format!("{s} 에 설치기의 표시({STAGING_MARKER})가 없습니다"))?;
    if exists(old) {
        if !has_bundle(old) {
            return Err(format!(
                "{o} 이(가) 이미 있고 MCP Monitor 설치 폴더(bundle.json)가 아닙니다"
            ));
        }
        fs::remove_dir_all(old).map_err(|e| format!("{o} 을(를) 지우지 못했습니다: {e}"))?;
    }
    let mut moved_old = false;
    if exists(install_dir) {
        if has_bundle(install_dir) {
            fs_ops
                .rename(install_dir, old)
                .map_err(|e| format!("{i} 을(를) {o} 로 옮기지 못했습니다: {e}"))?;
            moved_old = true;
        } else {
            // Ruling F12: an empty folder an administrator made beforehand (the plan accepted it).
            fs::remove_dir(install_dir).map_err(|e| {
                format!(
                    "{i} 이(가) 비어 있지 않고 MCP Monitor 설치 폴더(bundle.json)도 아닙니다: {e}"
                )
            })?;
        }
    }
    let put_old_back = |why: String| -> String {
        if moved_old && let Err(e) = fs_ops.rename(old, install_dir) {
            return format!("{why} (이전 설치 폴더 {o} 을(를) {i} 로 되돌리지 못했습니다: {e})");
        }
        why
    };
    if let Err(e) = fs_ops.rename(staging, install_dir) {
        return Err(put_old_back(format!(
            "{s} 을(를) {i} 로 옮기지 못했습니다: {e}. 이전 설치로 되돌립니다"
        )));
    }
    let roll_back = |why: String| -> String {
        if let Err(e) = fs_ops.rename(install_dir, staging) {
            return format!("{why} (새 설치 폴더를 {s} 로 되돌리지 못했습니다: {e})");
        }
        // The staging folder stays recognisable, so the next run's `stage` may remove it.
        let _ = fs::write(&marker_path, &marker);
        put_old_back(why)
    };
    if let Err(e) = fs::remove_file(install_dir.join(STAGING_MARKER)) {
        return Err(roll_back(format!(
            "{i} 의 {STAGING_MARKER} 을(를) 지우지 못했습니다: {e}. 이전 설치로 되돌립니다"
        )));
    }
    if let Some(why) = install_tree_problem(install_dir, owners) {
        return Err(roll_back(format!("{why}. 이전 설치로 되돌립니다")));
    }
    Ok(())
}

/// Removes the earlier install moved aside by [`swap`] (only a folder with `bundle.json`).
pub fn remove_old(old: &Path) -> Result<(), String> {
    let o = old.display();
    if !has_bundle(old) {
        return Err(format!(
            "{o} 은(는) MCP Monitor 설치 폴더(bundle.json)가 아니어서 지우지 않습니다"
        ));
    }
    fs::remove_dir_all(old).map_err(|e| format!("{o} 을(를) 지우지 못했습니다: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::acl::AUTHENTICATED_USERS;
    use crate::install::testutil::*;
    use crate::payload::STAGING_MARKER;
    use crate::payload_pack::pack_dir;
    use std::cell::Cell;
    use std::fs;
    use std::path::PathBuf;

    fn source(s: &Scratch, kind: &str) -> PayloadSource {
        let src = s.path().join("payload");
        fs::create_dir_all(src.join("bin/monitor")).unwrap();
        fs::write(
            src.join("bundle.json"),
            r#"{"layout":"pyinstaller","version":"1.1.0","agent":"desktop"}"#,
        )
        .unwrap();
        fs::write(src.join("bin/monitor/mcp-monitor-server.exe"), b"MZ server").unwrap();
        let p = pack_dir(&src, 3).unwrap();
        PayloadSource {
            archive: p.archive,
            sha256: p.sha256,
            manifest: p.manifest,
            kind: kind.into(),
        }
    }

    fn self_exe(s: &Scratch) -> PathBuf {
        let p = s.path().join("downloads").join("mcp-monitor-1.1.0.exe");
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        fs::write(&p, b"MZ self").unwrap();
        p
    }

    #[test]
    fn stage_extracts_the_payload_and_copies_this_exe() {
        let s = Scratch::new();
        let staging = s.path().join("i.staging");
        let written = stage(&staging, &source(&s, "release"), &self_exe(&s)).unwrap();
        assert_eq!(
            fs::read(staging.join("mcp-monitor.exe")).unwrap(),
            b"MZ self"
        );
        assert!(
            staging.join("bin/monitor/mcp-monitor-server.exe").is_file()
                && staging.join(STAGING_MARKER).is_file()
        );
        let bundle = fs::metadata(staging.join("bundle.json")).unwrap().len();
        assert_eq!(
            written,
            bundle + b"MZ server".len() as u64 + b"MZ self".len() as u64
        );
    }

    #[test]
    fn stage_refuses_the_fixture_payload() {
        let s = Scratch::new();
        let staging = s.path().join("i.staging");
        assert!(
            stage(&staging, &source(&s, "fixture"), &self_exe(&s))
                .unwrap_err()
                .contains("개발용")
        );
        assert!(!staging.exists());
    }

    #[test]
    fn stage_refuses_a_wrong_archive_hash_before_making_anything() {
        let s = Scratch::new();
        let staging = s.path().join("i.staging");
        let mut src = source(&s, "release");
        src.sha256 = "0".repeat(64);
        assert!(
            stage(&staging, &src, &self_exe(&s))
                .unwrap_err()
                .contains("해시")
        );
        assert!(!staging.exists());
    }

    #[test]
    fn stage_refuses_a_staging_folder_it_did_not_make() {
        let s = Scratch::new();
        let staging = s.path().join("i.staging");
        fs::create_dir(&staging).unwrap();
        fs::write(staging.join("keep.txt"), "x").unwrap();
        let e = stage(&staging, &source(&s, "release"), &self_exe(&s)).unwrap_err();
        assert!(e.contains("설치기가 만든 폴더가 아닙니다"), "{e}");
        assert!(staging.join("keep.txt").is_file());
        fs::remove_file(staging.join("keep.txt")).unwrap();
        fs::write(staging.join(STAGING_MARKER), "{}").unwrap(); // an earlier, unfinished staging of ours
        fs::write(staging.join("leftover.txt"), "x").unwrap();
        stage(&staging, &source(&s, "release"), &self_exe(&s)).unwrap();
        assert!(!staging.join("leftover.txt").exists() && staging.join("bundle.json").is_file());
    }

    #[test]
    fn the_installer_refuses_to_run_from_the_install_folder() {
        // Ruling F06: case-insensitive, also the .staging and .old neighbours.
        let inst = Path::new(r"C:\Program Files\MCP Monitor");
        for exe in [
            r"C:\Program Files\MCP Monitor\mcp-monitor.exe",
            r"c:\program files\mcp monitor\MCP-MONITOR.EXE",
            r"C:\Program Files\MCP Monitor.old\mcp-monitor.exe",
            r"C:\Program Files\MCP Monitor.staging\mcp-monitor.exe",
        ] {
            let e = running_inside_problem(Path::new(exe), inst, "1.1.0").expect(exe);
            assert!(
                e.contains("다운로드한 mcp-monitor-1.1.0.exe로 실행하세요"),
                "{e}"
            );
        }
        for exe in [
            r"C:\Users\a\Downloads\mcp-monitor-1.1.0.exe",
            r"C:\Program Files\MCP Monitor Other\mcp-monitor.exe",
        ] {
            assert_eq!(
                running_inside_problem(Path::new(exe), inst, "1.1.0"),
                None,
                "{exe}"
            );
        }
    }

    fn tree(dir: &Path, version: &str) {
        fs::create_dir_all(dir).unwrap();
        fs::write(dir.join("bundle.json"), version).unwrap();
    }

    fn dirs(s: &Scratch) -> (PathBuf, PathBuf, PathBuf) {
        (
            s.path().join("i.staging"),
            s.path().join("i"),
            s.path().join("i.old"),
        )
    }

    #[test]
    fn swap_moves_the_old_install_aside_and_puts_staging_in_place() {
        let s = Scratch::new();
        let (staging, inst, old) = dirs(&s);
        tree(&inst, "old");
        tree(&staging, "new");
        fs::write(staging.join(STAGING_MARKER), "{}").unwrap();
        swap(&staging, &inst, &old, &StdFs, &owners()).unwrap();
        assert_eq!(fs::read_to_string(inst.join("bundle.json")).unwrap(), "new");
        assert_eq!(fs::read_to_string(old.join("bundle.json")).unwrap(), "old");
        assert!(!staging.exists() && !inst.join(STAGING_MARKER).exists());
        remove_old(&old).unwrap();
        assert!(!old.exists());
    }

    #[test]
    fn swap_into_a_missing_install_dir() {
        let s = Scratch::new();
        let (staging, inst, old) = dirs(&s);
        tree(&staging, "new");
        fs::write(staging.join(STAGING_MARKER), "{}").unwrap();
        swap(&staging, &inst, &old, &StdFs, &owners()).unwrap();
        assert!(inst.join("bundle.json").is_file() && !old.exists());
    }

    #[test]
    fn swap_replaces_an_empty_install_dir() {
        // Ruling F12: an administrator may have made the (empty) folder beforehand.
        let s = Scratch::new();
        let (staging, inst, old) = dirs(&s);
        fs::create_dir(&inst).unwrap();
        tree(&staging, "new");
        fs::write(staging.join(STAGING_MARKER), "{}").unwrap();
        swap(&staging, &inst, &old, &StdFs, &owners()).unwrap();
        assert_eq!(fs::read_to_string(inst.join("bundle.json")).unwrap(), "new");
        assert!(!old.exists() && !staging.exists());
    }

    #[test]
    fn swap_refuses_folders_that_are_not_ours() {
        let s = Scratch::new();
        let (staging, inst, old) = dirs(&s);
        tree(&staging, "new");
        // No marker: not a staging folder of ours.
        assert!(swap(&staging, &inst, &old, &StdFs, &owners()).is_err());
        fs::write(staging.join(STAGING_MARKER), "{}").unwrap();
        // An install folder that holds something else.
        fs::create_dir(&inst).unwrap();
        fs::write(inst.join("x.txt"), "x").unwrap();
        assert!(swap(&staging, &inst, &old, &StdFs, &owners()).is_err());
        assert!(inst.join("x.txt").is_file() && staging.join("bundle.json").is_file());
        fs::remove_file(inst.join("x.txt")).unwrap();
        fs::write(inst.join("bundle.json"), "old").unwrap();
        // An .old folder that is not an install folder is never deleted.
        fs::create_dir(&old).unwrap();
        fs::write(old.join("y.txt"), "y").unwrap();
        assert!(swap(&staging, &inst, &old, &StdFs, &owners()).is_err());
        assert!(old.join("y.txt").is_file());
        assert_eq!(fs::read_to_string(inst.join("bundle.json")).unwrap(), "old");
        // An .old install folder left by an earlier upgrade is replaced.
        fs::remove_file(old.join("y.txt")).unwrap();
        fs::write(old.join("bundle.json"), "older").unwrap();
        swap(&staging, &inst, &old, &StdFs, &owners()).unwrap();
        assert_eq!(fs::read_to_string(old.join("bundle.json")).unwrap(), "old");
    }

    struct FailSecond(Cell<u32>);
    impl FsOps for FailSecond {
        fn rename(&self, from: &Path, to: &Path) -> io::Result<()> {
            self.0.set(self.0.get() + 1);
            if self.0.get() == 2 {
                return Err(io::Error::from_raw_os_error(32)); // ERROR_SHARING_VIOLATION: a file is still open
            }
            StdFs.rename(from, to)
        }
    }

    #[test]
    fn swap_rolls_back_when_staging_cannot_be_moved() {
        let s = Scratch::new();
        let (staging, inst, old) = dirs(&s);
        tree(&inst, "old");
        tree(&staging, "new");
        fs::write(staging.join(STAGING_MARKER), "{}").unwrap();
        assert!(swap(&staging, &inst, &old, &FailSecond(Cell::new(0)), &owners()).is_err());
        assert_eq!(fs::read_to_string(inst.join("bundle.json")).unwrap(), "old");
        assert!(staging.join("bundle.json").is_file() && !old.exists());
    }

    #[test]
    fn std_fs_reports_the_windows_error() {
        let s = Scratch::new();
        let e = StdFs
            .rename(&s.path().join("missing"), &s.path().join("x"))
            .unwrap_err();
        assert_eq!(e.raw_os_error(), Some(2), "{e}"); // ERROR_FILE_NOT_FOUND
    }

    #[test]
    fn swap_refuses_an_install_tree_others_may_write() {
        let s = Scratch::new();
        let (staging, inst, old) = dirs(&s);
        tree(&inst, "old");
        tree(&staging, "new");
        fs::write(staging.join(STAGING_MARKER), "{}").unwrap();
        grant(&staging.join("bundle.json"), "(W)");
        let e = swap(&staging, &inst, &old, &StdFs, &owners()).unwrap_err();
        assert!(e.contains(AUTHENTICATED_USERS), "{e}");
        assert_eq!(fs::read_to_string(inst.join("bundle.json")).unwrap(), "old");
        assert!(!old.exists());
        // The new tree is back in the staging folder, still marked as ours for the next run.
        assert_eq!(
            fs::read_to_string(staging.join("bundle.json")).unwrap(),
            "new"
        );
        assert!(staging.join(STAGING_MARKER).is_file());
    }

    #[test]
    fn remove_old_refuses_a_folder_without_bundle_json() {
        let s = Scratch::new();
        let old = s.path().join("i.old");
        fs::create_dir(&old).unwrap();
        fs::write(old.join("x"), "x").unwrap();
        assert!(remove_old(&old).is_err());
        assert!(old.join("x").is_file());
    }
}
