//! `(stop-apps)`: ends every process whose image lies in the install folder (a session's tray
//! app, an agent the stopped service left behind), so the folder can be moved aside (Y15). The
//! service itself was stopped by the step before.

use crate::install::paths::is_inside;
use crate::winutil::Owned;
use std::ffi::OsString;
use std::os::windows::ffi::OsStringExt;
use std::path::{Path, PathBuf};
use windows::Win32::Foundation::{
    ERROR_INVALID_PARAMETER, ERROR_NOT_ALL_ASSIGNED, GetLastError, HANDLE, LUID, WAIT_OBJECT_0,
};
use windows::Win32::Security::{
    AdjustTokenPrivileges, LUID_AND_ATTRIBUTES, LookupPrivilegeValueW, SE_DEBUG_NAME,
    SE_PRIVILEGE_ENABLED, TOKEN_ADJUST_PRIVILEGES, TOKEN_PRIVILEGES, TOKEN_QUERY,
};
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, PROCESSENTRY32W, Process32FirstW, Process32NextW, TH32CS_SNAPPROCESS,
};
use windows::Win32::System::Threading::{
    GetCurrentProcess, OpenProcess, OpenProcessToken, PROCESS_NAME_WIN32,
    PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_SYNCHRONIZE, PROCESS_TERMINATE,
    QueryFullProcessImageNameW, TerminateProcess, WaitForSingleObject,
};
use windows::core::{PCWSTR, PWSTR};

/// How long each ended process may take to go away.
const WAIT_MS: u32 = 5000;

/// The image names the install folder holds: a process with one of these names that cannot be
/// looked into even with `SeDebugPrivilege` might hold the folder open (ruling F07).
const APP_IMAGES: [&str; 2] = ["mcp-monitor.exe", "mcp-monitor-server.exe"];

/// The pids of `procs` (pid, full image path) whose image lies inside `install_dir` (ignoring
/// case), without the pids in `keep`.
pub fn select_app_processes(procs: &[(u32, String)], install_dir: &Path, keep: &[u32]) -> Vec<u32> {
    procs
        .iter()
        .filter(|(pid, image)| !keep.contains(pid) && is_inside(Path::new(image), install_dir))
        .map(|(pid, _)| *pid)
        .collect()
}

/// Ruling F07: an administrator's token holds `SeDebugPrivilege` (disabled); enabled, it opens
/// other users' processes, whose DACL does not grant Administrators. False when it is not held
/// (a standard account: only its own processes can be looked into anyway).
fn enable_debug_privilege() -> bool {
    let mut token = HANDLE::default();
    // SAFETY: the pseudo handle of this process; the token handle is owned and closed below.
    if unsafe {
        OpenProcessToken(
            GetCurrentProcess(),
            TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
            &mut token,
        )
    }
    .is_err()
    {
        return false;
    }
    let token = Owned(token);
    let mut luid = LUID::default();
    // SAFETY: the privilege name is a static NUL-terminated string; `luid` is a valid out pointer.
    if unsafe { LookupPrivilegeValueW(PCWSTR::null(), SE_DEBUG_NAME, &mut luid) }.is_err() {
        return false;
    }
    let privileges = TOKEN_PRIVILEGES {
        PrivilegeCount: 1,
        Privileges: [LUID_AND_ATTRIBUTES {
            Luid: luid,
            Attributes: SE_PRIVILEGE_ENABLED,
        }],
    };
    // SAFETY: a valid token handle and a TOKEN_PRIVILEGES with one entry; no previous state wanted.
    let adjusted =
        unsafe { AdjustTokenPrivileges(token.0, false, Some(&privileges), 0, None, None) };
    // AdjustTokenPrivileges succeeds with ERROR_NOT_ALL_ASSIGNED when the token lacks it.
    // SAFETY: reads this thread's last error right after the call.
    adjusted.is_ok() && unsafe { GetLastError() } != ERROR_NOT_ALL_ASSIGNED
}

/// The process has already exited (opening a pid that is gone fails with this).
fn gone(e: &windows::core::Error) -> bool {
    e.code() == ERROR_INVALID_PARAMETER.to_hresult()
}

/// The full Win32 image path of `pid`.
fn image_of(pid: u32) -> windows::core::Result<PathBuf> {
    // SAFETY: a plain open; the handle is owned and closed on drop.
    let process = Owned(unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) }?);
    let mut buf = vec![0u16; 32768];
    let mut len = buf.len() as u32;
    // SAFETY: the buffer holds `len` UTF-16 units.
    unsafe {
        QueryFullProcessImageNameW(
            process.0,
            PROCESS_NAME_WIN32,
            PWSTR(buf.as_mut_ptr()),
            &mut len,
        )
    }?;
    buf.truncate(len as usize);
    Ok(PathBuf::from(OsString::from_wide(&buf)))
}

/// Every running process as (pid, image path), and the pid and name of those whose image could
/// not be read (other than ones that exited meanwhile).
#[allow(clippy::type_complexity)]
fn running_processes() -> Result<(Vec<(u32, String)>, Vec<(u32, String)>), String> {
    // SAFETY: a snapshot handle we own and close on drop.
    let snapshot = Owned(
        unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) }
            .map_err(|e| format!("실행 중인 프로세스 목록을 읽지 못했습니다: {e}"))?,
    );
    let mut entry = PROCESSENTRY32W {
        dwSize: size_of::<PROCESSENTRY32W>() as u32,
        ..Default::default()
    };
    let (mut readable, mut unreadable) = (Vec::new(), Vec::new());
    // SAFETY: `entry` is a PROCESSENTRY32W with its size set.
    let mut more = unsafe { Process32FirstW(snapshot.0, &mut entry) }.is_ok();
    while more {
        let pid = entry.th32ProcessID;
        // pid 0 (Idle) and 4 (System) have no image file.
        if pid > 4 {
            match image_of(pid) {
                Ok(image) => readable.push((pid, image.display().to_string())),
                Err(e) if gone(&e) => {}
                Err(_) => {
                    let n = entry.szExeFile.iter().position(|&c| c == 0).unwrap_or(260);
                    unreadable.push((pid, String::from_utf16_lossy(&entry.szExeFile[..n])));
                }
            }
        }
        // SAFETY: as above.
        more = unsafe { Process32NextW(snapshot.0, &mut entry) }.is_ok();
    }
    Ok((readable, unreadable))
}

/// Ends (`TerminateProcess`, exit code 1) every process whose image lies in `install_dir`, other
/// than this one and the non-elevated copy of this exe that waits for it (an `--interactive`
/// uninstall started from the installed `mcp-monitor.exe` by Apps & features), and waits up to
/// 5 s for each. A process named like ours that cannot be looked into is an error, not a skip
/// (F07): it may hold the folder. Returns the (pid, image) of each process it ended (review item 5:
/// the step prints them, and a test can tell "not selected" from "ended").
pub fn stop_apps(install_dir: &Path) -> Result<Vec<(u32, String)>, String> {
    enable_debug_privilege();
    let keep: Vec<u32> = std::iter::once(std::process::id())
        .chain(crate::winutil::same_exe_parent())
        .collect();
    let (readable, unreadable) = running_processes()?;
    if let Some((pid, name)) = unreadable.iter().find(|(pid, name)| {
        !keep.contains(pid) && APP_IMAGES.iter().any(|a| a.eq_ignore_ascii_case(name))
    }) {
        return Err(format!(
            "{pid} {name} 을(를) 열 수 없어 설치 폴더의 프로그램인지 확인하지 못했습니다"
        ));
    }
    let mut ended = Vec::new();
    for pid in select_app_processes(&readable, install_dir, &keep) {
        let image = readable
            .iter()
            .find(|(p, _)| *p == pid)
            .map(|(_, i)| i.clone())
            .unwrap_or_default();
        // SAFETY: a plain open; the handle is owned and closed on drop.
        let process =
            match unsafe { OpenProcess(PROCESS_TERMINATE | PROCESS_SYNCHRONIZE, false, pid) } {
                Ok(h) => Owned(h),
                Err(e) if gone(&e) => continue,
                Err(e) => return Err(format!("{pid} {image} 을(를) 끝내지 못했습니다: {e}")),
            };
        // A process that is already exiting refuses; the wait below tells whether it went.
        // SAFETY: a handle opened with PROCESS_TERMINATE.
        let _ = unsafe { TerminateProcess(process.0, 1) };
        ended.push((pid, image, process));
    }
    let mut done = Vec::with_capacity(ended.len());
    for (pid, image, process) in ended {
        // SAFETY: a handle opened with PROCESS_SYNCHRONIZE.
        if unsafe { WaitForSingleObject(process.0, WAIT_MS) } != WAIT_OBJECT_0 {
            return Err(format!("{pid} {image} 이(가) 끝나지 않았습니다"));
        }
        done.push((pid, image));
    }
    Ok(done)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::testutil::*;
    use std::process::{Command, Stdio};

    #[test]
    fn stop_apps_targets_only_processes_inside_the_install_dir() {
        let procs = [
            (
                10,
                r"C:\Program Files\MCP Monitor\mcp-monitor.exe".to_string(),
            ),
            (11, r"C:\Program Files\MCP Monitor Other\x.exe".to_string()),
            (
                12,
                r"c:\program files\mcp monitor\BIN\monitor\mcp-monitor-server.exe".to_string(),
            ),
            (13, r"C:\Users\a\Downloads\mcp-monitor.exe".to_string()),
            (
                14,
                r"C:\Program Files\MCP Monitor\mcp-monitor.exe".to_string(),
            ),
        ];
        assert_eq!(
            select_app_processes(&procs, Path::new(r"C:\Program Files\MCP Monitor"), &[14]),
            [10, 12]
        );
        // An --interactive uninstall from the installed exe: the waiting non-elevated copy (10)
        // is kept too.
        assert_eq!(
            select_app_processes(
                &procs,
                Path::new(r"C:\Program Files\MCP Monitor"),
                &[14, 10]
            ),
            [12]
        );
        // The test exe was started by cargo, not by a copy of itself.
        assert_eq!(crate::winutil::same_exe_parent(), None);
    }

    /// `cmd.exe /d /k` waiting for commands on a pipe that stays open: a process that runs until
    /// it is ended. `exe` is the image to start.
    fn waiting_cmd(exe: &Path) -> std::process::Child {
        Command::new(exe)
            .args(["/d", "/q", "/k"])
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap()
    }

    #[test]
    fn stop_apps_ends_a_process_running_from_the_install_dir_and_nothing_else() {
        let s = Scratch::new();
        let inst = s.path().join("MCP Monitor");
        std::fs::create_dir_all(inst.join("bin")).unwrap();
        let copy = inst.join("bin").join("cmd.exe");
        std::fs::copy(crate::winutil::system_tool("cmd.exe"), &copy).unwrap();
        let mut inside = waiting_cmd(&copy);
        let mut outside = waiting_cmd(&crate::winutil::system_tool("cmd.exe"));
        // Review item 5: both are running before stop_apps, and the copy's image is seen inside
        // the install folder; otherwise a failure below would not say which part went wrong.
        std::thread::sleep(std::time::Duration::from_millis(300));
        assert!(
            inside.try_wait().unwrap().is_none(),
            "the copy exited by itself: {:?}",
            inside.try_wait()
        );
        let image = image_of(inside.id()).unwrap();
        assert!(
            is_inside(&image, &inst),
            "image {} is not inside {}",
            image.display(),
            inst.display()
        );
        let ended = stop_apps(&inst).unwrap();
        assert_eq!(
            ended.iter().map(|(pid, _)| *pid).collect::<Vec<_>>(),
            [inside.id()],
            "{ended:?}"
        );
        assert_eq!(
            inside.wait().unwrap().code(),
            Some(1),
            "ended with exit code 1"
        );
        assert!(
            outside.try_wait().unwrap().is_none(),
            "a process outside the install folder keeps running"
        );
        outside.kill().unwrap();
        outside.wait().unwrap();
        // Nothing left to end: still fine.
        assert!(stop_apps(&inst).unwrap().is_empty());
    }
}
