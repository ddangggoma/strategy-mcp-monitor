//! Small Win32 helpers.

use std::ffi::{OsString, c_void};
use std::os::windows::ffi::OsStringExt;
use std::path::{Path, PathBuf};
use windows::Win32::Foundation::{
    CloseHandle, ERROR_CANCELLED, HANDLE, HLOCAL, LocalFree, WAIT_OBJECT_0,
};
use windows::Win32::Security::Authorization::ConvertSidToStringSidW;
use windows::Win32::Security::{
    GetTokenInformation, TOKEN_ELEVATION, TOKEN_QUERY, TOKEN_USER, TokenElevation, TokenUser,
};
use windows::Win32::System::Console::{
    ATTACH_PARENT_PROCESS, AttachConsole, GetStdHandle, STD_OUTPUT_HANDLE,
};
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, PROCESSENTRY32W, Process32FirstW, Process32NextW, TH32CS_SNAPPROCESS,
};
use windows::Win32::System::LibraryLoader::{
    LOAD_LIBRARY_SEARCH_SYSTEM32, SetDefaultDllDirectories,
};
use windows::Win32::System::SystemInformation::GetSystemDirectoryW;
use windows::Win32::System::Threading::{
    GetCurrentProcess, GetExitCodeProcess, INFINITE, OpenProcess, OpenProcessToken,
    PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION, QueryFullProcessImageNameW,
    WaitForSingleObject,
};
use windows::Win32::UI::Shell::{
    CommandLineToArgvW, SEE_MASK_FLAG_NO_UI, SEE_MASK_NOASYNC, SEE_MASK_NOCLOSEPROCESS,
    SHELLEXECUTEINFOW, ShellExecuteExW,
};
use windows::Win32::UI::WindowsAndMessaging::{
    IDNO, IDYES, MB_ICONERROR, MB_ICONINFORMATION, MB_ICONQUESTION, MB_OK, MB_SETFOREGROUND,
    MB_TOPMOST, MB_YESNO, MESSAGEBOX_RESULT, MESSAGEBOX_STYLE, MessageBoxW, SW_SHOWNORMAL,
};
use windows::core::{HSTRING, PCWSTR, PWSTR, w};

/// Restricts this process's DLL search to System32 (Y13; Task 1 spike: `SYSTEM32` works with
/// WebView2). The first line of `main`, before anything can load a DLL by name: a DLL planted next
/// to a downloaded exe is then never loaded. Exits 1 if Windows refuses (fail closed).
pub fn harden_dll_search() {
    // SAFETY: plain flag call with no pointers.
    if unsafe { SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32) }.is_err() {
        std::process::exit(1);
    }
}

/// The exe is GUI-subsystem: when started from a console without redirected output, attach to the
/// parent's console so CLI output shows (Y13). Does nothing when standard output already exists
/// (a pipe or file) or when there is no parent console (service, Explorer).
pub fn attach_parent_console() {
    // SAFETY: plain calls with no pointers.
    unsafe {
        if GetStdHandle(STD_OUTPUT_HANDLE).is_err() {
            let _ = AttachConsole(ATTACH_PARENT_PROCESS);
        }
    }
}

/// An open handle that is closed when dropped.
struct Owned(HANDLE);

impl Drop for Owned {
    fn drop(&mut self) {
        // SAFETY: the handle was opened by us and is closed once.
        let _ = unsafe { CloseHandle(self.0) };
    }
}

fn process_token() -> windows::core::Result<Owned> {
    let mut token = HANDLE::default();
    // SAFETY: the out pointer is valid; the pseudo handle of the current process needs no closing.
    unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) }?;
    Ok(Owned(token))
}

/// True when this process runs with an elevated (administrator) token. False if Windows cannot
/// tell, so callers that need administrator rights refuse rather than proceed.
pub fn is_elevated() -> bool {
    let Ok(token) = process_token() else {
        return false;
    };
    let mut elevation = TOKEN_ELEVATION::default();
    let mut len = 0u32;
    // SAFETY: the buffer is a TOKEN_ELEVATION of the stated size.
    let ok = unsafe {
        GetTokenInformation(
            token.0,
            TokenElevation,
            Some(&mut elevation as *mut TOKEN_ELEVATION as *mut c_void),
            size_of::<TOKEN_ELEVATION>() as u32,
            &mut len,
        )
    }
    .is_ok();
    ok && elevation.TokenIsElevated != 0
}

/// Test guard for every test that can change something: tests never run elevated (Y23).
pub fn assert_not_elevated() {
    if is_elevated() {
        panic!("tests must not run elevated: they could change this PC");
    }
}

/// The SID of the account this process runs as, e.g. `S-1-5-21-…-1001`.
pub fn current_user_sid() -> String {
    let token = process_token().expect("OpenProcessToken failed");
    let mut len = 0u32;
    // SAFETY: a size query with no buffer; it fails with "insufficient buffer" and sets `len`.
    let _ = unsafe { GetTokenInformation(token.0, TokenUser, None, 0, &mut len) };
    assert!(
        len as usize >= size_of::<TOKEN_USER>(),
        "TokenUser size query failed"
    );
    // u64 storage keeps the TOKEN_USER (which holds pointers) aligned.
    let mut buf = vec![0u64; (len as usize).div_ceil(8)];
    // SAFETY: the buffer holds at least `len` bytes.
    unsafe {
        GetTokenInformation(
            token.0,
            TokenUser,
            Some(buf.as_mut_ptr() as *mut c_void),
            len,
            &mut len,
        )
    }
    .expect("GetTokenInformation(TokenUser) failed");
    // SAFETY: Windows filled the aligned buffer with a TOKEN_USER whose SID points into it.
    let sid = unsafe { (*(buf.as_ptr() as *const TOKEN_USER)).User.Sid };
    let mut text = PWSTR::null();
    // SAFETY: `sid` is valid while `buf` lives; the string is freed with LocalFree below.
    unsafe { ConvertSidToStringSidW(sid, &mut text) }.expect("ConvertSidToStringSidW failed");
    // SAFETY: `text` is a NUL-terminated string Windows allocated.
    let out = String::from_utf16_lossy(unsafe { text.as_wide() });
    // SAFETY: allocated by ConvertSidToStringSidW with LocalAlloc.
    unsafe { LocalFree(Some(HLOCAL(text.0 as *mut c_void))) };
    out
}

/// Splits a command line the way Windows (`CommandLineToArgvW`) does.
pub fn command_line_to_argv(line: &str) -> Vec<String> {
    let wide = HSTRING::from(line);
    let mut n = 0i32;
    // SAFETY: `wide` is NUL-terminated; the result is freed with LocalFree below.
    let argv = unsafe { CommandLineToArgvW(&wide, &mut n) };
    assert!(
        !argv.is_null(),
        "CommandLineToArgvW failed: {}",
        std::io::Error::last_os_error()
    );
    let out = (0..n as usize)
        // SAFETY: `argv` holds `n` NUL-terminated strings.
        .map(|i| String::from_utf16_lossy(unsafe { (*argv.add(i)).as_wide() }))
        .collect();
    // SAFETY: one LocalAlloc block holds the array and the strings.
    unsafe { LocalFree(Some(HLOCAL(argv as *mut c_void))) };
    out
}

/// The full Win32 path of process `pid`'s image, if it can be opened for a limited query.
fn process_image(pid: u32) -> Option<PathBuf> {
    // SAFETY: a plain open; the handle is owned and closed below.
    let process =
        Owned(unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) }.ok()?);
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
    }
    .ok()?;
    buf.truncate(len as usize);
    Some(PathBuf::from(OsString::from_wide(&buf)))
}

/// The id of the process that started this one (from a process snapshot).
fn parent_process_id() -> Option<u32> {
    // SAFETY: a snapshot handle we own and close below.
    let snapshot = Owned(unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) }.ok()?);
    let me = std::process::id();
    let mut entry = PROCESSENTRY32W {
        dwSize: size_of::<PROCESSENTRY32W>() as u32,
        ..Default::default()
    };
    // SAFETY: `entry` is a PROCESSENTRY32W with its size set.
    let mut more = unsafe { Process32FirstW(snapshot.0, &mut entry) }.is_ok();
    while more {
        if entry.th32ProcessID == me {
            return Some(entry.th32ParentProcessID);
        }
        // SAFETY: as above.
        more = unsafe { Process32NextW(snapshot.0, &mut entry) }.is_ok();
    }
    None
}

/// Paths compared the way Windows names files: ignoring case (F04).
fn same_path(a: &Path, b: &Path) -> bool {
    a.to_string_lossy().to_lowercase() == b.to_string_lossy().to_lowercase()
}

/// True when the process that started this one runs this same exe, i.e. this is the copy that
/// [`elevate_and_wait`] started. That copy never relaunches itself again, even if "runas" did not
/// elevate it (UAC turned off for a standard user): no endless chain of waiting processes.
pub fn parent_is_same_exe() -> bool {
    let (Some(parent), Ok(me)) = (parent_process_id(), std::env::current_exe()) else {
        return false;
    };
    process_image(parent).is_some_and(|image| same_path(&image, &me))
}

/// Turns a `ShellExecuteExW` failure into the Korean message the user sees.
fn elevation_error(e: &windows::core::Error) -> String {
    if e.code() == ERROR_CANCELLED.to_hresult() {
        "관리자 권한 요청이 취소되었습니다.".to_string()
    } else {
        format!("관리자 권한으로 다시 실행하지 못했습니다: {}", e.message())
    }
}

/// Runs `exe` elevated (UAC "runas") with `args` quoted by [`crate::cli::join_command_line`],
/// waits for it and returns its exit code. A cancelled UAC prompt is an error.
pub fn elevate_and_wait(exe: &Path, args: &[String]) -> Result<i32, String> {
    let file = HSTRING::from(exe);
    let parameters = HSTRING::from(crate::cli::join_command_line(args));
    let mut info = SHELLEXECUTEINFOW {
        cbSize: size_of::<SHELLEXECUTEINFOW>() as u32,
        fMask: SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC | SEE_MASK_FLAG_NO_UI,
        lpVerb: w!("runas"),
        lpFile: PCWSTR(file.as_ptr()),
        lpParameters: PCWSTR(parameters.as_ptr()),
        nShow: SW_SHOWNORMAL.0,
        ..Default::default()
    };
    // SAFETY: `info` and the strings it points to outlive the call.
    unsafe { ShellExecuteExW(&mut info) }.map_err(|e| elevation_error(&e))?;
    if info.hProcess.is_invalid() {
        return Err("관리자 권한으로 다시 실행하지 못했습니다: 프로세스 핸들이 없습니다".into());
    }
    let process = Owned(info.hProcess);
    // SAFETY: a valid process handle we own.
    if unsafe { WaitForSingleObject(process.0, INFINITE) } != WAIT_OBJECT_0 {
        return Err(format!(
            "관리자 권한으로 실행한 프로세스를 기다리지 못했습니다: {}",
            std::io::Error::last_os_error()
        ));
    }
    let mut code = 0u32;
    // SAFETY: a valid process handle and out pointer.
    unsafe { GetExitCodeProcess(process.0, &mut code) }.map_err(|e| {
        format!(
            "관리자 권한으로 실행한 프로세스의 종료 코드를 읽지 못했습니다: {}",
            e.message()
        )
    })?;
    Ok(code as i32)
}

pub const MESSAGE_BOX_TITLE: &str = "MCP Monitor";

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum MsgKind {
    Info,
    Error,
    YesNo,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum MsgAnswer {
    Ok,
    Yes,
    No,
}

fn message_box_style(kind: MsgKind) -> MESSAGEBOX_STYLE {
    let base = match kind {
        MsgKind::Info => MB_OK | MB_ICONINFORMATION,
        MsgKind::Error => MB_OK | MB_ICONERROR,
        MsgKind::YesNo => MB_YESNO | MB_ICONQUESTION,
    };
    base | MB_SETFOREGROUND | MB_TOPMOST
}

fn answer_from(result: MESSAGEBOX_RESULT) -> MsgAnswer {
    match result {
        IDYES => MsgAnswer::Yes,
        IDNO => MsgAnswer::No,
        _ => MsgAnswer::Ok,
    }
}

/// A topmost "MCP Monitor" message box; blocks until the user answers.
pub fn message_box(text: &str, kind: MsgKind) -> MsgAnswer {
    // SAFETY: both strings are NUL-terminated and outlive the call.
    let result = unsafe {
        MessageBoxW(
            None,
            &HSTRING::from(text),
            &HSTRING::from(MESSAGE_BOX_TITLE),
            message_box_style(kind),
        )
    };
    answer_from(result)
}

/// The absolute System32 folder (`GetSystemDirectoryW`). Panics if Windows cannot tell it,
/// rather than fall back to a relative name that would resolve in the current folder.
pub fn system_dir() -> PathBuf {
    let mut buf = vec![0u16; 260];
    loop {
        // SAFETY: the buffer is valid for writes of its whole length.
        let n = unsafe { GetSystemDirectoryW(Some(&mut buf)) } as usize;
        assert!(
            n != 0,
            "GetSystemDirectoryW failed: {}",
            std::io::Error::last_os_error()
        );
        if n < buf.len() {
            buf.truncate(n);
            return PathBuf::from(OsString::from_wide(&buf));
        }
        // Too small: `n` is the size needed, including the terminating null.
        buf.resize(n, 0);
    }
}

/// A System32 tool by its absolute path (`sc.exe`, `auditpol.exe`, …). Never searches the current
/// folder or `PATH`.
pub fn system_tool(name: &str) -> PathBuf {
    system_dir().join(name)
}

#[cfg(test)]
mod tests {
    use super::*;
    use windows::Win32::Foundation::ERROR_FILE_NOT_FOUND;
    use windows::Win32::UI::WindowsAndMessaging::{IDOK, MB_ICONMASK, MB_TYPEMASK};

    #[test]
    fn system_tools_live_in_the_absolute_system_directory() {
        let dir = system_dir();
        assert!(dir.is_absolute(), "{}", dir.display());
        assert!(
            dir.file_name()
                .unwrap()
                .to_string_lossy()
                .eq_ignore_ascii_case("System32"),
            "{}",
            dir.display()
        );
        assert_eq!(system_tool("sc.exe"), dir.join("sc.exe"));
        assert!(system_tool("cmd.exe").is_file());
    }

    fn whoami(args: &[&str]) -> String {
        let o = std::process::Command::new(system_tool("whoami.exe"))
            .args(args)
            .output()
            .unwrap();
        assert!(o.status.success());
        String::from_utf8_lossy(&o.stdout).into_owned()
    }

    #[test]
    fn current_user_sid_is_the_one_whoami_reports() {
        let sid = current_user_sid();
        assert!(sid.starts_with("S-1-5-"), "{sid}");
        // CSV: "domain\user","S-1-5-21-…"
        let line = whoami(&["/user", "/fo", "csv", "/nh"]);
        assert!(
            line.trim().ends_with(&format!("\"{sid}\"")),
            "{line:?} vs {sid}"
        );
    }

    #[test]
    fn elevation_agrees_with_the_mandatory_label() {
        // The high mandatory level (S-1-16-12288) is in the token exactly when it is elevated.
        let groups = whoami(&["/groups", "/fo", "csv", "/nh"]);
        assert_eq!(is_elevated(), groups.contains("S-1-16-12288"));
        assert_not_elevated();
    }

    #[test]
    fn command_line_to_argv_splits_like_the_c_runtime() {
        assert_eq!(
            command_line_to_argv(r#"x.exe a "b c" d\"e "" f\\"#),
            ["x.exe", "a", "b c", r#"d"e"#, "", r"f\\"]
        );
    }

    #[test]
    fn message_boxes_are_topmost_titled_and_answer_by_kind() {
        for kind in [MsgKind::Info, MsgKind::Error, MsgKind::YesNo] {
            let style = message_box_style(kind);
            assert_eq!(style & MB_SETFOREGROUND, MB_SETFOREGROUND, "{kind:?}");
            assert_eq!(style & MB_TOPMOST, MB_TOPMOST, "{kind:?}");
        }
        assert_eq!(message_box_style(MsgKind::Info) & MB_TYPEMASK, MB_OK);
        assert_eq!(
            message_box_style(MsgKind::Error) & MB_ICONMASK,
            MB_ICONERROR
        );
        assert_eq!(message_box_style(MsgKind::YesNo) & MB_TYPEMASK, MB_YESNO);
        assert_eq!(answer_from(IDYES), MsgAnswer::Yes);
        assert_eq!(answer_from(IDNO), MsgAnswer::No);
        assert_eq!(answer_from(IDOK), MsgAnswer::Ok);
        assert_eq!(MESSAGE_BOX_TITLE, "MCP Monitor");
    }

    #[test]
    fn process_images_and_the_parent_are_found() {
        let me = std::env::current_exe().unwrap();
        let mine = process_image(std::process::id()).unwrap();
        assert!(same_path(&mine, &me), "{mine:?} vs {me:?}");
        let parent = parent_process_id().unwrap();
        assert_ne!(parent, std::process::id());
        // The test runner is started by cargo or a shell, never by itself.
        assert!(!parent_is_same_exe());
        assert!(process_image(u32::MAX - 3).is_none());
        assert!(same_path(
            Path::new(r"C:\Program Files\MCP Monitor\MCP-Monitor.EXE"),
            Path::new(r"c:\program files\mcp monitor\mcp-monitor.exe")
        ));
        assert!(!same_path(
            Path::new(r"C:\a\x.exe"),
            Path::new(r"C:\b\x.exe")
        ));
    }

    #[test]
    fn a_cancelled_uac_prompt_reads_as_cancelled() {
        let cancelled = windows::core::Error::from_hresult(ERROR_CANCELLED.to_hresult());
        assert_eq!(
            elevation_error(&cancelled),
            "관리자 권한 요청이 취소되었습니다."
        );
        let other = windows::core::Error::from_hresult(ERROR_FILE_NOT_FOUND.to_hresult());
        assert!(elevation_error(&other).starts_with("관리자 권한으로 다시 실행하지 못했습니다: "));
    }
}
