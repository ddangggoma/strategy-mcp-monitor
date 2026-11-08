//! Path checks ported from Plan 5's PowerShell scripts (`Get-FullPath`, `Test-Inside`,
//! `Get-LocalDriveLetters`, `Get-PathLinkProblem`, `Get-UnsafeRootReason`, `Test-DataRootMarker`).
//!
//! Every path comparison here ignores case like PowerShell's `-eq` and `OrdinalIgnoreCase`
//! (Ruling F04): compare `full_path` output with [`same_path`] / [`is_inside`], never with `==`
//! on `Path` or `str`.

use std::collections::HashMap;
use std::io;
use std::path::{Path, PathBuf};
use windows::Win32::Storage::FileSystem::{
    FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_REPARSE_POINT, GetDriveTypeW, GetFileAttributesW,
    GetFullPathNameW, GetVolumeNameForVolumeMountPointW, INVALID_FILE_ATTRIBUTES,
};
use windows::core::HSTRING;

/// `GetDriveTypeW`: a fixed disk (`DRIVE_FIXED` lives in a feature this crate does not enable).
const DRIVE_FIXED: u32 = 3;

/// The environment variables the path checks read (`Env::from_process`).
pub const ENV_KEYS: [&str; 10] = [
    "SystemRoot",
    "SystemDrive",
    "ProgramData",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "ProgramW6432",
    "PUBLIC",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
];

/// The folder variables of [`ENV_KEYS`]; tests and plan builders use a fake one.
pub struct Env(pub HashMap<String, String>);

impl Env {
    /// The [`ENV_KEYS`] of this process, names matched ignoring case.
    pub fn from_process() -> Env {
        let mut map = HashMap::new();
        for (k, v) in std::env::vars_os() {
            let (Some(k), Some(v)) = (k.to_str(), v.to_str()) else {
                continue;
            };
            if let Some(key) = ENV_KEYS.iter().find(|key| key.eq_ignore_ascii_case(k)) {
                map.insert(key.to_string(), v.to_string());
            }
        }
        Env(map)
    }

    /// The value of `k` (name matched ignoring case); an empty value counts as missing, as
    /// PowerShell's `Where-Object { $_ }` drops it.
    pub fn get(&self, k: &str) -> Option<String> {
        self.0
            .iter()
            .find(|(key, _)| key.eq_ignore_ascii_case(k))
            .map(|(_, v)| v.clone())
            .filter(|v| !v.is_empty())
    }
}

/// The drive letters of this PC's local fixed volumes.
pub trait Volumes {
    fn local_fixed_letters(&self) -> Vec<char>;
}

/// The real volumes: `A`–`Z` whose root is a fixed disk with a volume of its own. A `subst` drive
/// has no volume (`GetVolumeNameForVolumeMountPointW` fails), a network or removable drive is not
/// fixed: none of them is listed (as `Win32_Volume` with `DriveType = 3` in Plan 5).
pub struct SystemVolumes;

impl Volumes for SystemVolumes {
    fn local_fixed_letters(&self) -> Vec<char> {
        ('A'..='Z')
            .filter(|l| {
                let root = HSTRING::from(format!("{l}:\\"));
                // SAFETY: `root` is a NUL-terminated string that outlives the call.
                if unsafe { GetDriveTypeW(&root) } != DRIVE_FIXED {
                    return false;
                }
                // A volume GUID path is 49 characters plus the NUL.
                let mut name = [0u16; 64];
                // SAFETY: as above; the buffer is valid for writes of its whole length.
                unsafe { GetVolumeNameForVolumeMountPointW(&root, &mut name) }.is_ok()
            })
            .collect()
    }
}

/// Characters .NET Framework's `Path.GetFullPath` refuses (and that no folder name may hold).
fn has_invalid_chars(p: &str) -> bool {
    p.chars()
        .any(|c| (c as u32) < 0x20 || matches!(c, '<' | '>' | '"' | '|' | '?' | '*'))
}

/// `Get-FullPath`: the absolute form of `p` (`GetFullPathNameW`, relative to the current
/// folder), without trailing `\` unless it is a drive root. The case is kept as written. A path
/// that cannot be a folder (`<>"|?*`, control characters, a `:` after the drive) is an error,
/// as .NET Framework refuses it.
pub fn full_path(p: &str) -> Result<PathBuf, String> {
    let fail = |why: &str| format!("경로 {p} 을(를) 해석할 수 없습니다: {why}");
    if p.is_empty() {
        return Err(fail("빈 경로입니다"));
    }
    if has_invalid_chars(p) {
        return Err(fail("경로에 쓸 수 없는 문자가 있습니다"));
    }
    let wide = HSTRING::from(p);
    let mut buf = vec![0u16; 300];
    let n = loop {
        // SAFETY: `wide` is NUL-terminated; the buffer is valid for writes of its whole length.
        let n = unsafe { GetFullPathNameW(&wide, Some(&mut buf), None) } as usize;
        if n == 0 {
            return Err(fail(&io::Error::last_os_error().to_string()));
        }
        if n < buf.len() {
            break n;
        }
        // Too small: `n` is the size needed, including the terminating NUL.
        buf.resize(n, 0);
    };
    let mut full = String::from_utf16(&buf[..n]).map_err(|e| fail(&e.to_string()))?;
    // A second ':' names an alternate data stream (or nothing at all): never a folder.
    if full.char_indices().any(|(i, c)| c == ':' && i != 1) {
        return Err(fail("드라이브 뒤에 ':'가 있습니다"));
    }
    if full.len() > 3 {
        full.truncate(full.trim_end_matches('\\').len());
    }
    Ok(PathBuf::from(full))
}

/// One character as `OrdinalIgnoreCase` compares it: its simple upper-case form.
fn fold_char(c: char) -> char {
    let mut upper = c.to_uppercase();
    match (upper.next(), upper.next()) {
        (Some(u), None) => u,
        _ => c,
    }
}

/// `p` in the form every comparison uses: `\` separators, no trailing `\`, case folded.
fn folded(p: &Path) -> String {
    p.to_string_lossy()
        .replace('/', "\\")
        .trim_end_matches('\\')
        .chars()
        .map(fold_char)
        .collect()
}

/// PowerShell's `-eq` on two `full_path` results: the same path ignoring case and trailing
/// separators (`C:\ProgramData` = `c:\programdata\`).
pub fn same_path(a: &Path, b: &Path) -> bool {
    folded(a) == folded(b)
}

/// `Test-Inside`: `child` lies below `parent` (`parent\` is a prefix, ignoring case). A folder
/// is not inside itself.
pub fn is_inside(child: &Path, parent: &Path) -> bool {
    let child: String = child
        .to_string_lossy()
        .replace('/', "\\")
        .chars()
        .map(fold_char)
        .collect();
    child.starts_with(&format!("{}\\", folded(parent)))
}

/// The attributes of `path` itself (a link is not followed), as `File.GetAttributes` reads them.
pub(crate) fn attributes(path: &Path) -> io::Result<u32> {
    // SAFETY: the HSTRING is NUL-terminated and outlives the call.
    let a = unsafe { GetFileAttributesW(&HSTRING::from(path)) };
    if a == INVALID_FILE_ATTRIBUTES {
        return Err(io::Error::last_os_error());
    }
    Ok(a)
}

pub(crate) fn is_reparse(attributes: u32) -> bool {
    attributes & FILE_ATTRIBUTE_REPARSE_POINT.0 != 0
}

pub(crate) fn is_directory(attributes: u32) -> bool {
    attributes & FILE_ATTRIBUTE_DIRECTORY.0 != 0
}

/// `X:\` when `full` starts with a drive letter, a colon and a backslash.
fn drive_prefix(full: &str) -> Option<&str> {
    let b = full.as_bytes();
    (b.len() >= 3 && b[0].is_ascii_alphabetic() && b[1] == b':' && b[2] == b'\\')
        .then(|| &full[..3])
}

/// `Get-PathLinkProblem`: the first existing folder from the drive down to `full` itself that is
/// a junction or symbolic link (`None`: none). Through one, another folder would pass the checks
/// under a different name. Stops at the first missing folder: nothing exists below it.
pub fn path_link_problem(full: &Path) -> Option<String> {
    let text = full.to_string_lossy();
    let Some(drive) = drive_prefix(&text) else {
        return Some(format!(
            "{text} 을(를) 확인하지 못했습니다: 드라이브 경로가 아닙니다"
        ));
    };
    let mut path = drive.trim_end_matches('\\').to_string();
    for part in text[3..].split('\\').filter(|p| !p.is_empty()) {
        path = format!("{path}\\{part}");
        match attributes(Path::new(&path)) {
            Ok(a) if is_reparse(a) => {
                return Some(format!(
                    "{path} 은(는) 정션 또는 심볼릭 링크입니다(경로에 둘 수 없음)"
                ));
            }
            Ok(_) => {}
            Err(e) if e.kind() == io::ErrorKind::NotFound => return None,
            Err(e) => return Some(format!("{path} 을(를) 확인하지 못했습니다: {e}")),
        }
    }
    None
}

/// `Get-UnsafeRootReason`: why `root` must not be a folder this program creates, fills or
/// deletes whole (the data root, the install folder); `None`: safe. Refused: `\\` or `//`
/// forms (UNC, admin shares, `\\?\` and `\\.\` device paths), anything that is not an absolute
/// drive-letter path (relative, `\x`, `C:x`), a drive that is not a local fixed volume, a
/// drive root, a junction or symbolic link in the path, a system folder or a folder above one,
/// and anything inside Windows. Every comparison ignores case (F04).
pub fn unsafe_root_reason(root: &str, env: &Env, vols: &dyn Volumes) -> Option<String> {
    let mut first = root.chars();
    if matches!(
        (first.next(), first.next()),
        (Some('\\' | '/'), Some('\\' | '/'))
    ) {
        return Some(format!(
            "{root} 은(는) 로컬 드라이브의 경로(예: D:\\MCP Monitor)가 아닙니다(UNC·장치 경로)"
        ));
    }
    let not_local = || {
        Some(format!(
            "{root} 은(는) 로컬 드라이브의 경로(예: D:\\MCP Monitor)가 아닙니다"
        ))
    };
    if drive_prefix(&root.replace('/', "\\")).is_none() {
        return not_local();
    }
    let full = match full_path(root) {
        Ok(f) => f,
        Err(e) => return Some(e),
    };
    let text = full.to_string_lossy().to_string();
    let Some(drive) = drive_prefix(&text) else {
        return not_local();
    };
    let letter = drive.chars().next().unwrap().to_ascii_uppercase();
    if !vols.local_fixed_letters().contains(&letter) {
        return Some(format!(
            "{} 은(는) 이 PC의 로컬 고정 디스크가 아닙니다(subst·네트워크·이동식 드라이브)",
            &text[..2]
        ));
    }
    if same_path(&full, Path::new(drive)) {
        return Some(format!("{text} 은(는) 드라이브 루트입니다"));
    }
    if let Some(link) = path_link_problem(&full) {
        return Some(link);
    }
    let public = env.get("PUBLIC");
    let public_parent = public
        .as_deref()
        .and_then(|p| Path::new(p).parent())
        .map(|p| p.display().to_string())
        .filter(|p| !p.is_empty());
    let system = [
        env.get("SystemRoot"),
        env.get("ProgramData"),
        env.get("ProgramFiles"),
        env.get("ProgramFiles(x86)"),
        env.get("ProgramW6432"),
        public_parent,
        public,
        env.get("USERPROFILE"),
        env.get("LOCALAPPDATA"),
        env.get("APPDATA"),
    ];
    for s in system.into_iter().flatten() {
        let s = match full_path(&s) {
            Ok(s) => s,
            Err(e) => return Some(e),
        };
        if same_path(&full, &s) || is_inside(&s, &full) {
            return Some(format!(
                "{text} 은(는) 시스템 폴더({})이거나 그 위 폴더입니다",
                s.display()
            ));
        }
    }
    // Without SystemRoot (never in a real process), the folder above System32.
    let windows = match env.get("SystemRoot") {
        Some(w) => full_path(&w),
        None => Ok(crate::winutil::system_dir()
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_default()),
    };
    match windows {
        Ok(w) if is_inside(&full, &w) => Some(format!("{text} 은(는) Windows 폴더 안입니다")),
        Ok(_) => None,
        Err(e) => Some(e),
    }
}

/// `Test-DataRootMarker`: a data root this product made (`data\mcp-monitor-data-root.json`, or
/// `data\install-state.json` from an install before the marker existed).
pub fn data_root_marker(root: &Path) -> bool {
    let data = root.join("data");
    data.join("mcp-monitor-data-root.json").is_file() || data.join("install-state.json").is_file()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::testutil::*;

    struct FakeVolumes(Vec<char>);
    impl Volumes for FakeVolumes {
        fn local_fixed_letters(&self) -> Vec<char> {
            self.0.clone()
        }
    }

    fn unc(p: &Path) -> String {
        let s = p.display().to_string();
        format!(r"\\localhost\{}$\{}", &s[..1], &s[3..])
    }

    #[test]
    fn unsafe_roots_are_refused() {
        let s = Scratch::new();
        let e = Env::from_process();
        let d = s.path().join("d");
        let cases = [
            format!("{}\\", e.get("SystemDrive").unwrap()),
            "Q:\\".to_string(),
            e.get("ProgramData").unwrap(),
            PathBuf::from(e.get("PUBLIC").unwrap())
                .parent()
                .unwrap()
                .display()
                .to_string(),
            format!(r"{}\Temp\mcp", e.get("SystemRoot").unwrap()),
            format!(r"\\?\{}", d.display()),
            format!(r"\\.\{}", d.display()),
            unc(&d),
            e.get("LOCALAPPDATA").unwrap(),
        ];
        for c in &cases {
            assert!(unsafe_root_reason(c, &e, &SystemVolumes).is_some(), "{c}");
        }
        assert_eq!(
            unsafe_root_reason(&d.display().to_string(), &e, &SystemVolumes),
            None
        );
    }

    #[test]
    fn unsafe_root_reason_needs_a_local_fixed_volume() {
        let s = Scratch::new();
        let e = Env::from_process();
        let letters = SystemVolumes.local_fixed_letters();
        assert!(
            letters.contains(
                &e.get("SystemDrive")
                    .unwrap()
                    .chars()
                    .next()
                    .unwrap()
                    .to_ascii_uppercase()
            )
        );
        let d = s.path().join("d").display().to_string();
        assert_eq!(unsafe_root_reason(&d, &e, &SystemVolumes), None);
        assert!(
            unsafe_root_reason(&d, &e, &FakeVolumes(vec!['Q']))
                .unwrap()
                .contains("로컬 고정 디스크가 아닙니다")
        );
    }

    #[test]
    fn a_junction_in_the_path_is_refused() {
        let s = Scratch::new();
        junction(&s.path().join("link"), &s.path().join("real"));
        let r = unsafe_root_reason(
            &s.path().join("link").join("d").display().to_string(),
            &Env::from_process(),
            &SystemVolumes,
        )
        .unwrap();
        assert!(r.contains("정션 또는 심볼릭 링크"), "{r}");
    }

    #[test]
    fn inside_is_case_insensitive_and_needs_a_separator() {
        assert!(is_inside(
            Path::new(r"C:\Program Files\MCP Monitor\bin"),
            Path::new(r"c:\program files\mcp monitor")
        ));
        assert!(!is_inside(
            Path::new(r"C:\Program Files\MCP Monitor2"),
            Path::new(r"C:\Program Files\MCP Monitor")
        ));
        assert!(!is_inside(Path::new(r"C:\x"), Path::new(r"C:\x")));
    }

    #[test]
    fn only_a_marked_data_root_counts_as_ours() {
        let s = Scratch::new();
        let (bare, marked, legacy) = (
            s.path().join("bare"),
            s.path().join("marked"),
            s.path().join("legacy"),
        );
        for r in [&bare, &marked, &legacy] {
            std::fs::create_dir_all(r.join("data")).unwrap();
        }
        std::fs::write(marked.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        std::fs::write(legacy.join("data/install-state.json"), "{}").unwrap();
        assert_eq!(
            [
                data_root_marker(&bare),
                data_root_marker(&marked),
                data_root_marker(&legacy)
            ],
            [false, true, true]
        );
        // A marker that is a folder, not a file, does not count (Test-Path -PathType Leaf).
        std::fs::create_dir_all(bare.join("data/install-state.json")).unwrap();
        assert!(!data_root_marker(&bare));
    }

    // --- additions beyond the plan's list ---------------------------------------------------

    #[test]
    fn full_path_trims_separators_but_keeps_the_drive_root() {
        assert_eq!(full_path(r"C:\x\y\").unwrap(), PathBuf::from(r"C:\x\y"));
        assert_eq!(full_path(r"C:\x\y\\").unwrap(), PathBuf::from(r"C:\x\y"));
        assert_eq!(full_path("C:/x/y/").unwrap(), PathBuf::from(r"C:\x\y"));
        assert_eq!(full_path(r"C:\x\..\y").unwrap(), PathBuf::from(r"C:\y"));
        assert_eq!(full_path(r"C:\").unwrap(), PathBuf::from(r"C:\"));
        // The case is kept as given: every comparison folds it instead (F04).
        assert_eq!(
            full_path(r"c:\Program Files").unwrap(),
            PathBuf::from(r"c:\Program Files")
        );
        let cwd = std::env::current_dir().unwrap();
        assert_eq!(full_path("rel").unwrap(), cwd.join("rel"));
        for bad in [
            "",
            "C:\\a\0b",
            r"C:\a<b",
            r"C:\a|b",
            "C:\\a\"b",
            r"C:\a?b",
            r"C:\a*b",
            r"C:\x:stream",
        ] {
            let e = full_path(bad).unwrap_err();
            assert!(e.contains("해석할 수 없습니다"), "{bad:?}: {e}");
        }
    }

    #[test]
    fn same_path_folds_case_and_trailing_separators() {
        assert!(same_path(
            Path::new(r"C:\ProgramData"),
            Path::new(r"c:\programdata\")
        ));
        assert!(same_path(Path::new(r"C:\"), Path::new(r"c:")));
        assert!(same_path(Path::new("C:/x/Y"), Path::new(r"c:\X\y")));
        assert!(!same_path(
            Path::new(r"C:\ProgramData"),
            Path::new(r"C:\ProgramData2")
        ));
        assert!(is_inside(Path::new(r"c:\x\y"), Path::new(r"C:\")));
        assert!(is_inside(Path::new("C:/X/y"), Path::new(r"c:\x")));
        assert!(!is_inside(Path::new(r"C:\xy"), Path::new(r"C:\x")));
    }

    #[test]
    fn env_reads_its_keys_ignoring_case() {
        let e = Env::from_process();
        for k in ENV_KEYS {
            assert_eq!(
                e.get(k),
                std::env::var(k).ok().filter(|v| !v.is_empty()),
                "{k}"
            );
        }
        assert!(e.get("SystemRoot").is_some());
        assert_eq!(e.get("systemroot"), e.get("SYSTEMROOT"));
        assert_eq!(e.get("PATH"), None, "only the listed keys are read");
        let fake = Env([("programdata".to_string(), r"D:\PD".to_string())]
            .into_iter()
            .collect());
        assert_eq!(fake.get("ProgramData").as_deref(), Some(r"D:\PD"));
        assert_eq!(
            Env([("PUBLIC".to_string(), String::new())]
                .into_iter()
                .collect())
            .get("PUBLIC"),
            None
        );
    }

    #[test]
    fn every_path_guard_ignores_case() {
        // F04: `c:\programdata` must be refused like `C:\ProgramData`, in both directions.
        let s = Scratch::new();
        let e = Env::from_process();
        let v = SystemVolumes;
        let sys = |k: &str| PathBuf::from(e.get(k).unwrap());
        let refused = [
            format!("{}\\", e.get("SystemDrive").unwrap().to_lowercase()),
            swap_case(&sys("ProgramData")),
            sys("ProgramData").display().to_string().to_lowercase(),
            sys("ProgramData").display().to_string().to_uppercase(),
            swap_case(sys("PUBLIC").parent().unwrap()),
            swap_case(&sys("PUBLIC")),
            swap_case(&sys("USERPROFILE")),
            swap_case(&sys("LOCALAPPDATA")),
            swap_case(&sys("APPDATA")),
            swap_case(&sys("ProgramFiles")),
            swap_case(&sys("SystemRoot")),
            swap_case(&sys("SystemRoot").join("Temp").join("mcp")),
            // a folder above a system folder, written in the other case
            swap_case(sys("LOCALAPPDATA").parent().unwrap()),
        ];
        for r in &refused {
            assert!(unsafe_root_reason(r, &e, &v).is_some(), "{r}");
        }
        let windows = unsafe_root_reason(&swap_case(&sys("SystemRoot").join("x")), &e, &v).unwrap();
        assert!(windows.contains("Windows 폴더 안"), "{windows}");
        let above = unsafe_root_reason(&swap_case(&sys("ProgramData")), &e, &v).unwrap();
        assert!(above.contains("시스템 폴더"), "{above}");
        // A lowercase drive letter is a local fixed volume too, and a safe folder stays safe in any case.
        let d = s.path().join("d");
        assert_eq!(unsafe_root_reason(&swap_case(&d), &e, &v), None);
        assert_eq!(
            unsafe_root_reason(&d.display().to_string().to_lowercase(), &e, &v),
            None
        );
        // The link check walks the path as written: a junction found under another case is still found.
        junction(&s.path().join("Link"), &s.path().join("real"));
        let linked = swap_case(&s.path().join("Link").join("d"));
        assert!(
            unsafe_root_reason(&linked, &e, &v)
                .unwrap()
                .contains("정션 또는 심볼릭 링크")
        );
        std::fs::create_dir_all(d.join("data")).unwrap();
        std::fs::write(d.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        assert!(data_root_marker(Path::new(&swap_case(&d))));
    }

    #[test]
    fn other_path_forms_are_refused() {
        let s = Scratch::new();
        let e = Env::from_process();
        let d = s.path().join("d").display().to_string();
        let forward = d.replace('\\', "/");
        let cases = [
            format!("//?/{forward}"),
            format!(r"\/?\{d}"),
            format!("//localhost/{}$/{}", &d[..1], &forward[3..]),
            format!(r"\\.\{d}"),
            "d".to_string(),
            r"\d".to_string(),
            format!("{}d", &d[..2]),
            // climbs to the drive root
            format!("{d}{}", r"\..".repeat(16)),
            format!("{d}:stream"),
        ];
        for c in &cases {
            assert!(unsafe_root_reason(c, &e, &SystemVolumes).is_some(), "{c}");
        }
        // The forward-slash form of a safe local path is the same path.
        assert_eq!(unsafe_root_reason(&forward, &e, &SystemVolumes), None);
    }

    #[test]
    fn path_link_problem_stops_at_a_missing_folder() {
        let s = Scratch::new();
        assert_eq!(path_link_problem(&s.path().join("missing").join("x")), None);
        junction(&s.path().join("link"), &s.path().join("real"));
        assert_eq!(path_link_problem(&s.path().join("real").join("x")), None);
        let p = path_link_problem(&s.path().join("link")).unwrap();
        assert!(
            p.contains("link") && p.contains("정션 또는 심볼릭 링크"),
            "{p}"
        );
    }

    #[test]
    fn system_volumes_are_upper_case_letters_with_a_volume() {
        let letters = SystemVolumes.local_fixed_letters();
        assert!(!letters.is_empty());
        assert!(
            letters.iter().all(|l| l.is_ascii_uppercase()),
            "{letters:?}"
        );
        let scratch_drive = std::env::var("LOCALAPPDATA")
            .unwrap()
            .chars()
            .next()
            .unwrap();
        assert!(letters.contains(&scratch_drive.to_ascii_uppercase()));
    }
}
