//! What the plan builders read from this PC (never write): administrator rights, the service,
//! the Apps & features entry, two registry values, folder variables, volumes, the account and the
//! embedded payload. [`SystemHost`] reads the real values; tests use [`FakeHost`].

use crate::install::paths::{Env, SystemVolumes, Volumes};
use std::ffi::c_void;
use std::path::PathBuf;
use windows::Win32::Foundation::ERROR_SUCCESS;
use windows::Win32::System::Registry::{
    HKEY_LOCAL_MACHINE, RRF_RT_REG_DWORD, RRF_RT_REG_SZ, RegGetValueW,
};
use windows::Win32::System::Services::{
    CloseServiceHandle, OpenSCManagerW, OpenServiceW, QUERY_SERVICE_CONFIGW, QueryServiceConfigW,
    QueryServiceStatus, SC_HANDLE, SC_MANAGER_CONNECT, SERVICE_QUERY_CONFIG, SERVICE_QUERY_STATUS,
    SERVICE_STATUS, SERVICE_STOPPED,
};
use windows::core::{HSTRING, PCWSTR};

/// The service the installer creates (`sc.exe create mcp-monitor …`).
pub const SERVICE_NAME: &str = "mcp-monitor";

/// The Apps & features entry of an install (Y19).
pub const UNINSTALL_KEY: &str =
    r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\MCPMonitor";

#[derive(Clone, Debug, PartialEq)]
pub struct Installed {
    pub version: String,
    pub install_location: PathBuf,
}

/// The embedded payload: its `bundle.json` version and layout, `payload::KIND`, and the
/// Apps & features size (payload files + this exe, in KiB).
#[derive(Clone, Debug, PartialEq)]
pub struct PayloadInfo {
    pub version: String,
    pub layout: String,
    pub kind: String,
    pub size_kb: u32,
}

pub trait Host {
    fn is_admin(&self) -> bool;
    /// `OpenSCManager(SC_MANAGER_CONNECT)` + `OpenService(SERVICE_QUERY_STATUS)`.
    fn service_exists(&self) -> bool;
    /// The service's command line (`QueryServiceConfigW`, no admin needed); `None` without a service.
    /// A 1.0.0 install made with `-InstallDir`/`-DataRoot` has nothing else that names its folders
    /// (ruling F13).
    fn service_bin_path(&self) -> Option<String>;
    /// True when the service is gone or `STOPPED` (the wait after `stop_existing`).
    fn service_stopped(&self) -> bool;
    /// `HKLM\…\Uninstall\MCPMonitor`: `DisplayVersion`, `InstallLocation`.
    fn installed(&self) -> Option<Installed>;
    /// `"<key>\<name>"` (`HKLM\…`) as a DWORD; `None` when missing or not a DWORD. Read only.
    fn registry_dword(&self, value: &str) -> Option<u32>;
    fn env(&self) -> &Env;
    fn volumes(&self) -> &dyn Volumes;
    fn user_sid(&self) -> String;
    fn payload(&self) -> PayloadInfo;
}

/// This PC, read only.
pub struct SystemHost {
    env: Env,
}

impl SystemHost {
    #[allow(clippy::new_without_default)]
    pub fn new() -> SystemHost {
        SystemHost {
            env: Env::from_process(),
        }
    }
}

/// A service-control handle that is closed when dropped.
struct Sc(SC_HANDLE);

impl Drop for Sc {
    fn drop(&mut self) {
        // SAFETY: the handle was opened by us and is closed once.
        let _ = unsafe { CloseServiceHandle(self.0) };
    }
}

/// Opens [`SERVICE_NAME`] with `access` (`None`: no such service, or no right to open it).
fn open_service(access: u32) -> Option<Sc> {
    // SAFETY: null machine and database names mean this PC's active database.
    let manager =
        Sc(unsafe { OpenSCManagerW(PCWSTR::null(), PCWSTR::null(), SC_MANAGER_CONNECT) }.ok()?);
    // SAFETY: the name is NUL-terminated and outlives the call; the manager handle is open.
    let service = unsafe { OpenServiceW(manager.0, &HSTRING::from(SERVICE_NAME), access) }.ok()?;
    Some(Sc(service))
}

/// `"HKLM\<key>\<name>"` split into the key below HKLM and the value name.
fn hklm_parts(value: &str) -> Option<(&str, &str)> {
    let rest = value
        .get(..5)
        .filter(|head| head.eq_ignore_ascii_case(r"HKLM\"))
        .map(|_| &value[5..])?;
    rest.rsplit_once('\\')
}

fn read_dword(key: &str, name: &str) -> Option<u32> {
    let mut data = 0u32;
    let mut size = size_of::<u32>() as u32;
    // SAFETY: both strings are NUL-terminated; `data` holds `size` bytes.
    let err = unsafe {
        RegGetValueW(
            HKEY_LOCAL_MACHINE,
            &HSTRING::from(key),
            &HSTRING::from(name),
            RRF_RT_REG_DWORD,
            None,
            Some(&mut data as *mut u32 as *mut c_void),
            Some(&mut size),
        )
    };
    (err == ERROR_SUCCESS).then_some(data)
}

fn read_string(key: &str, name: &str) -> Option<String> {
    let (key, name) = (HSTRING::from(key), HSTRING::from(name));
    let mut size = 0u32;
    // SAFETY: a size query with no buffer.
    let err = unsafe {
        RegGetValueW(
            HKEY_LOCAL_MACHINE,
            &key,
            &name,
            RRF_RT_REG_SZ,
            None,
            None,
            Some(&mut size),
        )
    };
    if err != ERROR_SUCCESS {
        return None;
    }
    let mut buf = vec![0u16; (size as usize).div_ceil(2) + 1];
    let mut size = (buf.len() * 2) as u32;
    // SAFETY: the buffer holds `size` bytes.
    let err = unsafe {
        RegGetValueW(
            HKEY_LOCAL_MACHINE,
            &key,
            &name,
            RRF_RT_REG_SZ,
            None,
            Some(buf.as_mut_ptr() as *mut c_void),
            Some(&mut size),
        )
    };
    if err != ERROR_SUCCESS {
        return None;
    }
    let len = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
    String::from_utf16(&buf[..len]).ok()
}

impl Host for SystemHost {
    fn is_admin(&self) -> bool {
        crate::winutil::is_elevated()
    }

    fn service_exists(&self) -> bool {
        open_service(SERVICE_QUERY_STATUS).is_some()
    }

    fn service_bin_path(&self) -> Option<String> {
        let service = open_service(SERVICE_QUERY_CONFIG)?;
        let mut needed = 0u32;
        // SAFETY: a size query with no buffer; it fails with "insufficient buffer" and sets `needed`.
        let _ = unsafe { QueryServiceConfigW(service.0, None, 0, &mut needed) };
        if (needed as usize) < size_of::<QUERY_SERVICE_CONFIGW>() {
            return None;
        }
        // u64 storage keeps the structure (which holds pointers) aligned.
        let mut buf = vec![0u64; (needed as usize).div_ceil(8)];
        let config = buf.as_mut_ptr() as *mut QUERY_SERVICE_CONFIGW;
        // SAFETY: the buffer holds `needed` bytes, aligned for the structure.
        unsafe { QueryServiceConfigW(service.0, Some(config), needed, &mut needed) }.ok()?;
        // SAFETY: Windows filled the structure; its strings point into `buf`, alive here.
        let path = unsafe { (*config).lpBinaryPathName };
        if path.is_null() {
            return None;
        }
        // SAFETY: a NUL-terminated string inside `buf`.
        String::from_utf16(unsafe { path.as_wide() }).ok()
    }

    fn service_stopped(&self) -> bool {
        let Some(service) = open_service(SERVICE_QUERY_STATUS) else {
            return !self.service_exists();
        };
        let mut status = SERVICE_STATUS::default();
        // SAFETY: a valid handle and out pointer.
        unsafe { QueryServiceStatus(service.0, &mut status) }.is_ok()
            && status.dwCurrentState == SERVICE_STOPPED
    }

    fn installed(&self) -> Option<Installed> {
        let key = &UNINSTALL_KEY[5..];
        Some(Installed {
            version: read_string(key, "DisplayVersion")?,
            install_location: PathBuf::from(read_string(key, "InstallLocation")?),
        })
    }

    fn registry_dword(&self, value: &str) -> Option<u32> {
        let (key, name) = hklm_parts(value)?;
        read_dword(key, name)
    }

    fn env(&self) -> &Env {
        &self.env
    }

    fn volumes(&self) -> &dyn Volumes {
        &SystemVolumes
    }

    fn user_sid(&self) -> String {
        crate::winutil::current_user_sid()
    }

    fn payload(&self) -> PayloadInfo {
        let m = crate::payload::manifest();
        let text = |k: &str| m.bundle[k].as_str().unwrap_or_default().to_string();
        let files: u64 = m.files.iter().map(|f| f.size).sum();
        let exe = std::env::current_exe()
            .and_then(std::fs::metadata)
            .map(|md| md.len())
            .unwrap_or(0);
        PayloadInfo {
            version: text("version"),
            layout: text("layout"),
            kind: crate::payload::KIND.to_string(),
            size_kb: u32::try_from(files / 1024 + exe / 1024).unwrap_or(u32::MAX),
        }
    }
}

/// A PC for tests: no administrator, no service, nothing installed, empty registry, this
/// process's folder variables and volumes, this account, the 1.1.0 release payload.
#[cfg(test)]
pub struct FakeHost {
    pub admin: bool,
    pub service: bool,
    /// The service's binPath (only read when `service` is true).
    pub bin_path: Option<String>,
    /// The service is still running (the wait after `stop_existing` never ends).
    pub running: bool,
    pub installed: Option<Installed>,
    pub dwords: std::collections::HashMap<String, u32>,
    pub env: Env,
    pub letters: Vec<char>,
    pub sid: String,
    pub payload: PayloadInfo,
}

#[cfg(test)]
impl FakeHost {
    #[allow(clippy::new_without_default)]
    pub fn new() -> FakeHost {
        FakeHost {
            admin: false,
            service: false,
            bin_path: None,
            running: false,
            installed: None,
            dwords: Default::default(),
            env: Env::from_process(),
            letters: SystemVolumes.local_fixed_letters(),
            sid: crate::install::testutil::me(),
            payload: PayloadInfo {
                version: "1.1.0".into(),
                layout: "pyinstaller".into(),
                kind: "release".into(),
                size_kb: 60000,
            },
        }
    }
}

#[cfg(test)]
impl Volumes for FakeHost {
    fn local_fixed_letters(&self) -> Vec<char> {
        self.letters.clone()
    }
}

#[cfg(test)]
impl Host for FakeHost {
    fn is_admin(&self) -> bool {
        self.admin
    }
    fn service_exists(&self) -> bool {
        self.service
    }
    fn service_bin_path(&self) -> Option<String> {
        self.bin_path.clone().filter(|_| self.service)
    }
    fn service_stopped(&self) -> bool {
        !self.running
    }
    fn installed(&self) -> Option<Installed> {
        self.installed.clone()
    }
    fn registry_dword(&self, value: &str) -> Option<u32> {
        self.dwords.get(value).copied()
    }
    fn env(&self) -> &Env {
        &self.env
    }
    fn volumes(&self) -> &dyn Volumes {
        self
    }
    fn user_sid(&self) -> String {
        self.sid.clone()
    }
    fn payload(&self) -> PayloadInfo {
        self.payload.clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn system_host_reads_this_pc_without_changing_it() {
        crate::winutil::assert_not_elevated();
        let h = SystemHost::new();
        assert!(!h.is_admin());
        // This development PC has no MCP Monitor service and no Apps & features entry.
        assert!(!h.service_exists() && h.service_stopped() && h.service_bin_path().is_none());
        assert_eq!(h.installed(), None);
        assert_eq!(h.user_sid(), crate::winutil::current_user_sid());
        assert!(h.volumes().local_fixed_letters().contains(&'C'));
        assert!(h.env().get("ProgramFiles").is_some());
        let p = h.payload();
        assert_eq!(
            (p.version.as_str(), p.layout.as_str(), p.kind.as_str()),
            ("1.1.0", "pyinstaller", crate::payload::KIND)
        );
        assert!(p.size_kb > 0);
        // A DWORD every Windows has; a missing one and a non-HKLM name read as None.
        assert!(
            h.registry_dword(r"HKLM\SYSTEM\CurrentControlSet\Control\Lsa\LimitBlankPasswordUse")
                .is_some()
        );
        assert_eq!(
            h.registry_dword(r"HKLM\SOFTWARE\MCP Monitor Test\Missing"),
            None
        );
        assert_eq!(h.registry_dword(r"HKCU\Environment\x"), None);
        assert_eq!(hklm_parts(r"hklm\A\B\c"), Some((r"A\B", "c")));
        assert_eq!(
            read_string(
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
                "CurrentBuild"
            )
            .map(|b| !b.is_empty()),
            Some(true)
        );
    }
}
