//! The start menu shortcut (Y19): a `.lnk` written with the shell's `IShellLinkW`.

use std::path::{Path, PathBuf};
use windows::Win32::Storage::FileSystem::WIN32_FIND_DATAW;
use windows::Win32::System::Com::{
    CLSCTX_INPROC_SERVER, COINIT_APARTMENTTHREADED, CoCreateInstance, CoInitializeEx,
    CoUninitialize, IPersistFile, STGM_READ,
};
use windows::Win32::UI::Shell::{IShellLinkW, SLGP_RAWPATH, ShellLink};
use windows::core::{HSTRING, Interface};

/// COM for this thread while it lives (apartment-threaded, as the shell objects want). A thread
/// already in another apartment keeps it; COM still works there.
struct Com(bool);

impl Com {
    fn init() -> Com {
        // SAFETY: no reserved pointer; balanced by CoUninitialize on drop when it succeeded.
        Com(unsafe { CoInitializeEx(None, COINIT_APARTMENTTHREADED) }.is_ok())
    }
}

impl Drop for Com {
    fn drop(&mut self) {
        if self.0 {
            // SAFETY: pairs the successful CoInitializeEx of this thread.
            unsafe { CoUninitialize() };
        }
    }
}

fn link() -> Result<IShellLinkW, String> {
    // SAFETY: the shell's ShellLink class, created in process.
    unsafe { CoCreateInstance(&ShellLink, None, CLSCTX_INPROC_SERVER) }
        .map_err(|e| format!("바로 가기 개체를 만들지 못했습니다: {}", e.message()))
}

/// Writes `lnk` → `target` with `args` and `description`; the working folder is the target's
/// folder. An existing `lnk` is replaced.
pub fn create_shortcut(
    lnk: &Path,
    target: &Path,
    args: &str,
    description: &str,
) -> Result<(), String> {
    let _com = Com::init();
    let fail = |e: windows::core::Error| {
        format!(
            "바로 가기 {} 을(를) 만들지 못했습니다: {}",
            lnk.display(),
            e.message()
        )
    };
    let link = link()?;
    let dir = target.parent().unwrap_or(target);
    // SAFETY: a live COM object; every string is NUL-terminated and outlives its call.
    unsafe {
        link.SetPath(&HSTRING::from(target)).map_err(fail)?;
        link.SetArguments(&HSTRING::from(args)).map_err(fail)?;
        link.SetDescription(&HSTRING::from(description))
            .map_err(fail)?;
        link.SetWorkingDirectory(&HSTRING::from(dir))
            .map_err(fail)?;
        let file: IPersistFile = link.cast().map_err(fail)?;
        file.Save(&HSTRING::from(lnk), true).map_err(fail)?;
    }
    refresh_shell_icons(&[lnk, target]);
    Ok(())
}

/// Tells the shell that `paths` changed and that cached icons are stale, so the start menu and
/// taskbar draw the new exe's icon instead of the one cached for that path by an older build.
fn refresh_shell_icons(paths: &[&Path]) {
    use windows::Win32::UI::Shell::{
        SHCNE_ASSOCCHANGED, SHCNE_UPDATEITEM, SHCNF_FLUSHNOWAIT, SHCNF_IDLIST, SHCNF_PATHW,
        SHChangeNotify,
    };
    for path in paths {
        let wide = HSTRING::from(*path);
        // SAFETY: a NUL-terminated path that outlives the call.
        unsafe {
            SHChangeNotify(
                SHCNE_UPDATEITEM,
                SHCNF_PATHW | SHCNF_FLUSHNOWAIT,
                Some(wide.as_ptr().cast()),
                None,
            )
        };
    }
    // SAFETY: no item pointers.
    unsafe {
        SHChangeNotify(
            SHCNE_ASSOCCHANGED,
            SHCNF_IDLIST | SHCNF_FLUSHNOWAIT,
            None,
            None,
        )
    };
}

/// The target and description of `lnk` (tests and diagnosis).
pub fn read_shortcut(lnk: &Path) -> Result<(PathBuf, String), String> {
    let _com = Com::init();
    let fail = |e: windows::core::Error| {
        format!(
            "바로 가기 {} 을(를) 읽지 못했습니다: {}",
            lnk.display(),
            e.message()
        )
    };
    let link = link()?;
    let mut path = vec![0u16; 32768];
    let mut description = vec![0u16; 1024];
    // SAFETY: a live COM object; the buffers are as long as the slices say.
    unsafe {
        let file: IPersistFile = link.cast().map_err(fail)?;
        file.Load(&HSTRING::from(lnk), STGM_READ).map_err(fail)?;
        let mut find = WIN32_FIND_DATAW::default();
        link.GetPath(&mut path, &mut find, SLGP_RAWPATH.0 as u32)
            .map_err(fail)?;
        link.GetDescription(&mut description).map_err(fail)?;
    }
    let text = |buf: &[u16]| {
        let end = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
        String::from_utf16_lossy(&buf[..end])
    };
    Ok((PathBuf::from(text(&path)), text(&description)))
}
