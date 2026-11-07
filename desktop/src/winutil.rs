//! Small Win32 helpers.

use std::ffi::OsString;
use std::os::windows::ffi::OsStringExt;
use std::path::PathBuf;
use windows::Win32::System::SystemInformation::GetSystemDirectoryW;

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
}
