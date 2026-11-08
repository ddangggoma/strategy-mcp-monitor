//! `harden_dll_search` in its own test process: it changes the process-wide DLL search order.

use windows::Win32::Foundation::{ERROR_BAD_EXE_FORMAT, ERROR_MOD_NOT_FOUND};
use windows::Win32::System::LibraryLoader::LoadLibraryW;
use windows::core::HSTRING;

fn load_error(name: &str) -> windows::core::HRESULT {
    // SAFETY: the planted file is not a PE image, so nothing is ever mapped or run.
    match unsafe { LoadLibraryW(&HSTRING::from(name)) } {
        Ok(module) => panic!("{name} loaded as {module:?}"),
        Err(e) => e.code(),
    }
}

#[test]
fn a_dll_planted_next_to_the_exe_is_not_found_after_hardening() {
    mcp_monitor::winutil::assert_not_elevated();
    // The application folder is what a Downloads-folder plant targets (Y13).
    let app_dir = std::env::current_exe()
        .unwrap()
        .parent()
        .unwrap()
        .to_path_buf();
    let mut b = [0u8; 6];
    getrandom::fill(&mut b).unwrap();
    let name = format!("mcpmon-planted-{}.dll", hex::encode(b));
    let planted = app_dir.join(&name);
    std::fs::write(&planted, b"not a dll").unwrap();
    struct Remove(std::path::PathBuf);
    impl Drop for Remove {
        fn drop(&mut self) {
            let _ = std::fs::remove_file(&self.0);
        }
    }
    let _cleanup = Remove(planted);

    // Without hardening the loader finds the plant (and refuses it only because it is not a PE).
    assert_eq!(load_error(&name), ERROR_BAD_EXE_FORMAT.to_hresult());
    mcp_monitor::winutil::harden_dll_search();
    assert_eq!(load_error(&name), ERROR_MOD_NOT_FOUND.to_hresult());
    // System32 DLLs still load by name.
    // SAFETY: a System32 DLL with no side effects on load.
    assert!(unsafe { LoadLibraryW(&HSTRING::from("version.dll")) }.is_ok());
}
