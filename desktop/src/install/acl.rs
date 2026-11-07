//! Data root, ancestor and install-folder ACL rules ported from Plan 5's PowerShell scripts with
//! the same rules (Y18): `Get-TreeItems`, `Get-UntrustedRule`, `Get-DataRootProblem`,
//! `Test-DataRootReadable`, `Get-FolderAcl`, `Get-AncestorProblem`, `Reset-ItemAcl`,
//! `New-RootSecurity`, `Set-RootAcl`, `New-ProtectedDirectory`, `Get-DataRootAclProblems`,
//! `Initialize-DataRoot`, plus the new `install_tree_problem` (Y15, ruling E1).
//!
//! The rule itself (`untrusted_rule`) is a pure function of the ACE list; Win32 sits in small
//! functions here. Masks are compared raw, as .NET's `FileSystemRights` are.

use crate::install::paths::{
    attributes, data_root_marker, full_path, is_directory, is_reparse, same_path,
};
use std::ffi::c_void;
use std::io;
use std::os::windows::fs::MetadataExt;
use std::path::{Path, PathBuf};
use windows::Win32::Foundation::{
    ERROR_ALREADY_EXISTS, ERROR_SUCCESS, HLOCAL, LocalFree, WIN32_ERROR,
};
use windows::Win32::Security::Authorization::{
    ConvertSecurityDescriptorToStringSecurityDescriptorW, ConvertSidToStringSidW,
    ConvertStringSecurityDescriptorToSecurityDescriptorW, ConvertStringSidToSidW,
    GetNamedSecurityInfoW, SDDL_REVISION_1, SE_FILE_OBJECT, SetNamedSecurityInfoW,
};
use windows::Win32::Security::{
    ACCESS_ALLOWED_ACE, ACE_HEADER, ACL, ACL_REVISION, DACL_SECURITY_INFORMATION, GetAce,
    GetSecurityDescriptorControl, GetSecurityDescriptorDacl, GetSecurityDescriptorOwner,
    InitializeAcl, OWNER_SECURITY_INFORMATION, PROTECTED_DACL_SECURITY_INFORMATION,
    PSECURITY_DESCRIPTOR, PSID, SE_DACL_PROTECTED, SECURITY_ATTRIBUTES,
    UNPROTECTED_DACL_SECURITY_INFORMATION,
};
use windows::Win32::Storage::FileSystem::CreateDirectoryW;
use windows::core::{BOOL, HSTRING, PWSTR};

pub const SYSTEM: &str = "S-1-5-18";
pub const ADMINISTRATORS: &str = "S-1-5-32-544";
pub const TRUSTED_INSTALLER: &str =
    "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464";
pub const AUTHENTICATED_USERS: &str = "S-1-5-11";
pub const EVERYONE: &str = "S-1-1-0";

pub const DELETE: u32 = 0x10000;
pub const WRITE_DAC: u32 = 0x40000;
pub const WRITE_OWNER: u32 = 0x80000;
pub const FILE_DELETE_CHILD: u32 = 0x40;
pub const GENERIC_ALL: u32 = 0x1000_0000;
pub const GENERIC_WRITE: u32 = 0x4000_0000;
pub const FILE_WRITE_DATA: u32 = 0x2;
pub const FILE_APPEND_DATA: u32 = 0x4;
pub const READ_EXECUTE: u32 = 0x0012_00A9;
/// Rights on a folder above the data root that let another account swap it (`Get-AncestorProblem`).
pub const ANCESTOR_RIGHTS: u32 = DELETE | WRITE_DAC | WRITE_OWNER | FILE_DELETE_CHILD | GENERIC_ALL;
/// Rights on the data root or an item in it that a handle opened before the install keeps
/// (`Get-DataRootProblem`).
pub const OPEN_RIGHTS: u32 = ANCESTOR_RIGHTS | GENERIC_WRITE | FILE_WRITE_DATA | FILE_APPEND_DATA;

pub const OBJECT_INHERIT_ACE: u8 = 0x1;
pub const CONTAINER_INHERIT_ACE: u8 = 0x2;
pub const INHERIT_ONLY_ACE: u8 = 0x8;
pub const INHERITED_ACE: u8 = 0x10;

/// .NET `FileSystemRights.FullControl` (SDDL `FA`).
const FULL_CONTROL: u32 = 0x1F_01FF;
const ACCESS_ALLOWED_ACE_TYPE: u8 = 0;
const ACCESS_DENIED_ACE_TYPE: u8 = 1;

/// One DACL entry. ACE types other than a plain allow or deny (object, callback, …) are read as
/// an allow of `GENERIC_ALL` for a placeholder SID: stricter than .NET, which skips them (F30).
#[derive(Clone, Debug, PartialEq)]
pub struct Ace {
    pub sid: String,
    pub allow: bool,
    pub mask: u32,
    pub flags: u8,
}

/// The owner and DACL of a file or folder (inherited ACEs included).
#[derive(Clone, Debug, PartialEq)]
pub struct SecurityInfo {
    pub owner: String,
    /// The DACL does not inherit from the parent (`SE_DACL_PROTECTED`).
    pub protected: bool,
    pub aces: Vec<Ace>,
}

/// One file or folder below a root, as listed (`reparse`: a junction, symbolic link or other
/// reparse point, never entered).
#[derive(Clone, Debug, PartialEq)]
pub struct Item {
    pub path: PathBuf,
    pub is_dir: bool,
    pub reparse: bool,
}

/// Memory Windows allocated with `LocalAlloc`, freed on drop.
struct Local(*mut c_void);

impl Drop for Local {
    fn drop(&mut self) {
        if !self.0.is_null() {
            // SAFETY: the block was allocated by a Win32 call that returns LocalAlloc memory and
            // is freed exactly once.
            unsafe { LocalFree(Some(HLOCAL(self.0))) };
        }
    }
}

fn win32(err: WIN32_ERROR) -> io::Result<()> {
    if err == ERROR_SUCCESS {
        Ok(())
    } else {
        Err(io::Error::from_raw_os_error(err.0 as i32))
    }
}

fn contains_sid(list: &[String], sid: &str) -> bool {
    list.iter().any(|s| s.eq_ignore_ascii_case(sid))
}

fn starts_with_ignore_case(s: &str, prefix: &str) -> bool {
    s.get(..prefix.len())
        .is_some_and(|head| head.eq_ignore_ascii_case(prefix))
}

/// `S-1-<digits>(-<digits>)+`: what may go into an SDDL string without changing its meaning.
fn is_sid(s: &str) -> bool {
    s.strip_prefix("S-1-").is_some_and(|rest| {
        rest.split('-')
            .all(|part| !part.is_empty() && part.bytes().all(|b| b.is_ascii_digit()))
    })
}

fn sid_string(sid: PSID) -> io::Result<String> {
    let mut text = PWSTR::null();
    // SAFETY: `sid` points to a valid SID inside a descriptor that outlives the call; the string
    // is freed by `Local`.
    unsafe { ConvertSidToStringSidW(sid, &mut text) }?;
    let _free = Local(text.0 as *mut c_void);
    // SAFETY: Windows wrote a NUL-terminated string.
    Ok(String::from_utf16_lossy(unsafe { text.as_wide() }))
}

/// The owner, protection flag and DACL of a descriptor.
///
/// # Safety
/// `sd` must point to a valid security descriptor that outlives the call.
unsafe fn security_from_descriptor(sd: PSECURITY_DESCRIPTOR) -> io::Result<SecurityInfo> {
    let mut defaulted = BOOL::default();
    let mut owner_sid = PSID::default();
    // SAFETY: `sd` is valid (caller); the out pointers are valid.
    unsafe { GetSecurityDescriptorOwner(sd, &mut owner_sid, &mut defaulted) }?;
    // A descriptor without an owner matches no owner list.
    let owner = if owner_sid.is_invalid() {
        String::new()
    } else {
        sid_string(owner_sid)?
    };
    let (mut control, mut revision) = (0u16, 0u32);
    // SAFETY: as above.
    unsafe { GetSecurityDescriptorControl(sd, &mut control, &mut revision) }?;
    let protected = control & SE_DACL_PROTECTED.0 != 0;
    let mut present = BOOL::default();
    let mut dacl: *mut ACL = std::ptr::null_mut();
    // SAFETY: as above.
    unsafe { GetSecurityDescriptorDacl(sd, &mut present, &mut dacl, &mut defaulted) }?;
    if !present.as_bool() || dacl.is_null() {
        // A NULL DACL gives everyone full access.
        let everyone = Ace {
            sid: EVERYONE.to_string(),
            allow: true,
            mask: GENERIC_ALL,
            flags: 0,
        };
        return Ok(SecurityInfo {
            owner,
            protected,
            aces: vec![everyone],
        });
    }
    // SAFETY: `dacl` points to the ACL inside the descriptor.
    let count = unsafe { (*dacl).AceCount };
    let mut aces = Vec::with_capacity(count as usize);
    for i in 0..u32::from(count) {
        let mut ace: *mut c_void = std::ptr::null_mut();
        // SAFETY: `i` is below the ACE count; `ace` receives a pointer into the ACL.
        unsafe { GetAce(dacl, i, &mut ace) }?;
        // SAFETY: every ACE starts with an ACE_HEADER.
        let header = unsafe { std::ptr::read_unaligned(ace as *const ACE_HEADER) };
        if header.AceType == ACCESS_ALLOWED_ACE_TYPE || header.AceType == ACCESS_DENIED_ACE_TYPE {
            // SAFETY: allow and deny ACEs share the ACCESS_ALLOWED_ACE layout; the SID starts at
            // `SidStart` and lies inside the ACE.
            let body = unsafe { std::ptr::read_unaligned(ace as *const ACCESS_ALLOWED_ACE) };
            let sid_at = std::mem::offset_of!(ACCESS_ALLOWED_ACE, SidStart);
            // SAFETY: the offset stays inside the ACE (see above).
            let sid = PSID(unsafe { (ace as *mut u8).add(sid_at) } as *mut c_void);
            aces.push(Ace {
                sid: sid_string(sid)?,
                allow: header.AceType == ACCESS_ALLOWED_ACE_TYPE,
                mask: body.Mask,
                flags: header.AceFlags,
            });
        } else {
            aces.push(Ace {
                sid: format!("(ACE 형식 {})", header.AceType),
                allow: true,
                mask: GENERIC_ALL,
                flags: header.AceFlags,
            });
        }
    }
    Ok(SecurityInfo {
        owner,
        protected,
        aces,
    })
}

/// The owner and DACL of `path` (`GetNamedSecurityInfoW`); a link is followed.
fn named_descriptor(path: &Path) -> io::Result<Local> {
    let mut sd = PSECURITY_DESCRIPTOR::default();
    // SAFETY: the name is NUL-terminated; `sd` receives a LocalAlloc block freed by `Local`.
    let err = unsafe {
        GetNamedSecurityInfoW(
            &HSTRING::from(path),
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            None,
            None,
            None,
            None,
            &mut sd,
        )
    };
    win32(err)?;
    Ok(Local(sd.0))
}

fn descriptor_from_sddl(sddl: &str) -> io::Result<Local> {
    let mut sd = PSECURITY_DESCRIPTOR::default();
    // SAFETY: the string is NUL-terminated; `sd` receives a LocalAlloc block freed by `Local`.
    unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            &HSTRING::from(sddl),
            SDDL_REVISION_1,
            &mut sd,
            None,
        )
    }?;
    Ok(Local(sd.0))
}

/// `Get-FolderAcl` and the ACL reads of every check: owner, protection and DACL of `path`.
pub fn read_security(path: &Path) -> io::Result<SecurityInfo> {
    let sd = named_descriptor(path)?;
    // SAFETY: `sd` holds a valid descriptor until it is dropped at the end of this function.
    unsafe { security_from_descriptor(PSECURITY_DESCRIPTOR(sd.0)) }
}

/// The owner and DACL of `path` as SDDL (tests and diagnostics).
pub fn sddl_of(path: &Path) -> io::Result<String> {
    let sd = named_descriptor(path)?;
    let mut text = PWSTR::null();
    // SAFETY: `sd` is a valid descriptor; the string is freed by `Local`.
    unsafe {
        ConvertSecurityDescriptorToStringSecurityDescriptorW(
            PSECURITY_DESCRIPTOR(sd.0),
            SDDL_REVISION_1,
            OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            &mut text,
            None,
        )
    }?;
    let _free = Local(text.0 as *mut c_void);
    // SAFETY: Windows wrote a NUL-terminated string.
    Ok(String::from_utf16_lossy(unsafe { text.as_wide() }))
}

#[cfg(test)]
fn security_from_sddl(sddl: &str) -> io::Result<SecurityInfo> {
    let sd = descriptor_from_sddl(sddl)?;
    // SAFETY: `sd` holds a valid descriptor until it is dropped at the end of this function.
    unsafe { security_from_descriptor(PSECURITY_DESCRIPTOR(sd.0)) }
}

/// The names of the dangerous rights in `mask` and the mask itself, for messages.
pub fn rights_text(mask: u32) -> String {
    const NAMES: [(u32, &str); 8] = [
        (GENERIC_ALL, "GENERIC_ALL"),
        (GENERIC_WRITE, "GENERIC_WRITE"),
        (DELETE, "DELETE"),
        (WRITE_DAC, "WRITE_DAC"),
        (WRITE_OWNER, "WRITE_OWNER"),
        (FILE_DELETE_CHILD, "FILE_DELETE_CHILD"),
        (FILE_WRITE_DATA, "FILE_WRITE_DATA"),
        (FILE_APPEND_DATA, "FILE_APPEND_DATA"),
    ];
    let names: Vec<&str> = NAMES
        .iter()
        .filter(|(bit, _)| mask & bit != 0)
        .map(|(_, name)| *name)
        .collect();
    if names.is_empty() {
        format!("0x{mask:08X}")
    } else {
        format!("{} (0x{mask:08X})", names.join(", "))
    }
}

/// `Get-UntrustedRule`: the first ACE that gives an account other than `owners` and
/// TrustedInstaller one of `rights` on the item itself (`None`: none). Deny ACEs, inherit-only
/// ACEs (they apply below, not to the item), CREATOR OWNER / OWNER RIGHTS placeholders
/// (`S-1-3-*`) and app-container SIDs (`S-1-15-*`, never enough alone) do not count.
pub fn untrusted_rule<'a>(aces: &'a [Ace], owners: &[String], rights: u32) -> Option<&'a Ace> {
    aces.iter().find(|a| {
        a.allow
            && a.flags & INHERIT_ONLY_ACE == 0
            && !contains_sid(owners, &a.sid)
            && !a.sid.eq_ignore_ascii_case(TRUSTED_INSTALLER)
            && !starts_with_ignore_case(&a.sid, "S-1-3-")
            && !starts_with_ignore_case(&a.sid, "S-1-15-")
            && a.mask & rights != 0
    })
}

/// `Get-TreeItems`: every file and folder below `root`, never entering a junction, symbolic link
/// or other reparse point (they are listed, flagged `reparse`).
pub fn tree_items(root: &Path) -> io::Result<Vec<Item>> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        for entry in std::fs::read_dir(&dir)? {
            let entry = entry?;
            // The listing's own attributes: a link is not followed.
            let a = entry.metadata()?.file_attributes();
            let item = Item {
                path: entry.path(),
                is_dir: is_directory(a),
                reparse: is_reparse(a),
            };
            if item.is_dir && !item.reparse {
                stack.push(item.path.clone());
            }
            out.push(item);
        }
    }
    Ok(out)
}

/// The root and every item below it pass: no link, owned by `owners`, no untrusted ACE with
/// `OPEN_RIGHTS`. `Ok(Err(problem))` refuses; `Err` is an I/O error (retried on NotFound).
fn check_data_root_items(
    root: &Path,
    owners: &[String],
    walk: &mut dyn FnMut(&Path) -> io::Result<Vec<Item>>,
) -> io::Result<Result<Vec<Item>, String>> {
    let items = walk(root)?;
    let root_item = Item {
        path: root.to_path_buf(),
        is_dir: true,
        reparse: false,
    };
    for item in std::iter::once(&root_item).chain(&items) {
        let name = item.path.display();
        if item.reparse {
            return Ok(Err(format!("{name} 은(는) 정션 또는 심볼릭 링크입니다")));
        }
        let sec = read_security(&item.path)?;
        if !contains_sid(owners, &sec.owner) {
            return Ok(Err(format!(
                "{name} 의 소유자({})가 SYSTEM·Administrators가 아닙니다",
                sec.owner
            )));
        }
        if let Some(rule) = untrusted_rule(&sec.aces, owners, OPEN_RIGHTS) {
            return Ok(Err(format!(
                "{name} 을(를) 관리자가 아닌 계정({})이 지우거나 쓰거나 권한·소유자를 바꿀 수 있습니다({}). \
                 그 권한으로 설치 전에 열어 둔 핸들은 설치가 권한을 바꾼 뒤에도 남습니다. \
                 {} 을(를) 지우고 설치가 새로 만들게 하세요(이전 데이터를 지킬 때는 그 권한을 없애고 PC를 다시 시작한 뒤 설치하세요)",
                rule.sid,
                rights_text(rule.mask),
                root.display()
            )));
        }
    }
    Ok(Ok(items))
}

/// `Get-DataRootProblem`: why an existing folder must not become the data root (`None`: safe or
/// missing). Only an empty folder or an earlier data root (marker) is taken over, and only when
/// `owners` own every item, nothing is a link, and no other account has `OPEN_RIGHTS` on the
/// root or an item below it (a handle opened before the install keeps them).
pub fn data_root_problem(root: &Path, owners: &[String]) -> Option<String> {
    data_root_problem_with(root, owners, &mut tree_items)
}

/// [`data_root_problem`] with the listing replaceable (tests). A file that goes away between the
/// listing and the ACL read (the service's log retention) gets one more look.
pub fn data_root_problem_with(
    root: &Path,
    owners: &[String],
    walk: &mut dyn FnMut(&Path) -> io::Result<Vec<Item>>,
) -> Option<String> {
    let shown = root.display();
    let a = match attributes(root) {
        Ok(a) => a,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return None,
        Err(e) => return Some(format!("{shown} 을(를) 확인하지 못했습니다: {e}")),
    };
    if !is_directory(a) {
        return Some(format!("{shown} 은(는) 폴더가 아닙니다"));
    }
    if is_reparse(a) {
        return Some(format!("{shown} 은(는) 정션 또는 심볼릭 링크입니다"));
    }
    let mut attempt = 1;
    let items = loop {
        match check_data_root_items(root, owners, walk) {
            Ok(Ok(items)) => break items,
            Ok(Err(problem)) => return Some(problem),
            Err(e) if attempt < 2 && e.kind() == io::ErrorKind::NotFound => attempt += 1,
            Err(e) => return Some(format!("{shown} 을(를) 확인하지 못했습니다: {e}")),
        }
    };
    if !items.is_empty() && !data_root_marker(root) {
        return Some(format!(
            "{shown} 이(가) 비어 있지 않고 MCP Monitor 데이터 폴더도 아닙니다"
        ));
    }
    None
}

/// `Test-DataRootReadable`: false only when the data root is a folder this account may not list
/// (an installed data root seen without admin rights).
pub fn data_root_readable(root: &Path) -> bool {
    if !attributes(root).is_ok_and(is_directory) {
        return true;
    }
    let denied = |e: &io::Error| e.kind() == io::ErrorKind::PermissionDenied;
    match std::fs::read_dir(root) {
        Ok(mut entries) => !matches!(entries.next(), Some(Err(e)) if denied(&e)),
        Err(e) => !denied(&e),
    }
}

/// `Get-AncestorProblem`: why the folders above `root` would let an account that is not an
/// administrator swap it (`None`: none). Every existing folder from the drive root down to the
/// parent must be owned by `owners` or TrustedInstaller and give no other account
/// `ANCESTOR_RIGHTS`; on the drive root `DELETE` does not count (it can be neither deleted nor
/// renamed). Stops at the first missing folder (it is made with the root's own ACL).
pub fn ancestor_problem(
    root: &Path,
    owners: &[String],
    folder_acl: &dyn Fn(&Path) -> io::Result<SecurityInfo>,
) -> Option<String> {
    let full = match full_path(&root.to_string_lossy()) {
        Ok(f) => f,
        Err(e) => return Some(e),
    };
    let mut trusted = owners.to_vec();
    trusted.push(TRUSTED_INSTALLER.to_string());
    let drive = full.ancestors().last()?;
    let mut chain: Vec<&Path> = full.ancestors().skip(1).collect();
    chain.reverse();
    for folder in chain {
        let shown = folder.display();
        match attributes(folder) {
            Ok(a) if is_directory(a) => {}
            Ok(_) => return None,
            Err(e) if e.kind() == io::ErrorKind::NotFound => return None,
            Err(e) => return Some(format!("{shown} 의 권한을 확인하지 못했습니다: {e}")),
        }
        let acl = match folder_acl(folder) {
            Ok(acl) => acl,
            Err(e) => return Some(format!("{shown} 의 권한을 확인하지 못했습니다: {e}")),
        };
        let (what, advice, rights) = if same_path(folder, drive) {
            (
                format!(
                    "드라이브 루트 {shown} 에서 관리자가 아닌 계정이 그 안의 폴더를 지우거나 이름을 바꾸거나 드라이브 루트의 권한을 바꿀 수 있습니다"
                ),
                "드라이브 루트의 그 권한을 없애거나 데이터 루트를 다른 드라이브에 두세요",
                ANCESTOR_RIGHTS & !DELETE,
            )
        } else {
            (
                format!(
                    "{shown} 을(를) 관리자가 아닌 계정이 지우거나 이름·권한을 바꿀 수 있습니다"
                ),
                "데이터 루트는 관리자만 바꿀 수 있는 폴더 아래나 드라이브 바로 아래(예: D:\\MCP Monitor)에 두세요",
                ANCESTOR_RIGHTS,
            )
        };
        if !contains_sid(&trusted, &acl.owner) {
            return Some(format!(
                "{shown} 의 소유자({})가 관리자가 아닙니다. {advice}",
                acl.owner
            ));
        }
        if let Some(rule) = untrusted_rule(&acl.aces, owners, rights) {
            return Some(format!(
                "{what}({}: {}). {advice}",
                rule.sid,
                rights_text(rule.mask)
            ));
        }
    }
    None
}

/// `New-RootSecurity`: the data root's descriptor built from scratch, never edited: owner
/// `owner`, inheritance off, full control for `sids` only, inherited by everything below.
pub struct RootSecurity {
    sd: Local,
    sddl: String,
}

impl RootSecurity {
    /// `O:<owner>D:P(A;OICI;FA;;;<sid>)…`. Only SIDs (`S-1-…`) are accepted, so nothing else can
    /// be spliced into the SDDL.
    pub fn new(owner: &str, sids: &[String]) -> io::Result<RootSecurity> {
        for sid in std::iter::once(owner).chain(sids.iter().map(String::as_str)) {
            if !is_sid(sid) {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    format!("SID가 아닙니다: {sid}"),
                ));
            }
        }
        let mut sddl = format!("O:{owner}D:P");
        for sid in sids {
            sddl.push_str(&format!("(A;OICI;FA;;;{sid})"));
        }
        let sd = descriptor_from_sddl(&sddl)?;
        Ok(RootSecurity { sd, sddl })
    }

    pub fn sddl(&self) -> &str {
        &self.sddl
    }

    fn descriptor(&self) -> PSECURITY_DESCRIPTOR {
        PSECURITY_DESCRIPTOR(self.sd.0)
    }

    /// The owner SID and the DACL inside the descriptor (valid while `self` lives).
    fn parts(&self) -> io::Result<(PSID, *const ACL)> {
        let mut defaulted = BOOL::default();
        let mut owner = PSID::default();
        // SAFETY: the descriptor is valid while `self` lives; the out pointers are valid.
        unsafe { GetSecurityDescriptorOwner(self.descriptor(), &mut owner, &mut defaulted) }?;
        let mut present = BOOL::default();
        let mut dacl: *mut ACL = std::ptr::null_mut();
        // SAFETY: as above.
        unsafe {
            GetSecurityDescriptorDacl(self.descriptor(), &mut present, &mut dacl, &mut defaulted)
        }?;
        if owner.is_invalid() || !present.as_bool() || dacl.is_null() {
            return Err(io::Error::other("보안 설명자에 소유자나 DACL이 없습니다"));
        }
        Ok((owner, dacl))
    }
}

/// `New-ProtectedDirectory`: creates `path` and every missing folder above it, each in one call
/// with the data root's final descriptor, so no moment exists in which one inherits its parent's
/// ACL. A folder that already exists is left as it is: the caller checks what it finds.
pub fn create_protected_dirs(path: &Path, sec: &RootSecurity) -> io::Result<()> {
    let mut missing = Vec::new();
    let mut dir = Some(path);
    while let Some(d) = dir.filter(|d| !d.as_os_str().is_empty()) {
        match attributes(d) {
            Ok(_) => break,
            Err(e) if e.kind() == io::ErrorKind::NotFound => {
                missing.push(d);
                dir = d.parent();
            }
            Err(e) => return Err(e),
        }
    }
    for d in missing.iter().rev() {
        let attrs = SECURITY_ATTRIBUTES {
            nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: sec.descriptor().0,
            bInheritHandle: false.into(),
        };
        // SAFETY: the name is NUL-terminated and `attrs` points to a descriptor that outlives the call.
        match unsafe { CreateDirectoryW(&HSTRING::from(*d), Some(&attrs)) } {
            Ok(()) => {}
            Err(e) if e.code() == ERROR_ALREADY_EXISTS.to_hresult() => {}
            Err(e) => return Err(e.into()),
        }
    }
    Ok(())
}

/// `Set-RootAcl`: owner and DACL of the root replaced by `sec`, inheritance from the parent off.
/// Windows re-applies the inherited ACEs below it.
pub fn set_root_acl(root: &Path, sec: &RootSecurity) -> io::Result<()> {
    let (owner, dacl) = sec.parts()?;
    // SAFETY: the name is NUL-terminated; `owner` and `dacl` point into `sec`, alive here.
    let err = unsafe {
        SetNamedSecurityInfoW(
            &HSTRING::from(root),
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION
                | DACL_SECURITY_INFORMATION
                | PROTECTED_DACL_SECURITY_INFORMATION,
            Some(owner),
            None,
            Some(dacl),
            None,
        )
    };
    win32(err)
}

/// `Reset-ItemAcl`: an item below the data root keeps no ACE of its own (only those inherited
/// from the root) and gets `owner`. A link is refused (looked at again, not only the listing).
pub fn reset_item_acl(item: &Item, owner: &str) -> io::Result<()> {
    if item.reparse || is_reparse(attributes(&item.path)?) {
        return Err(io::Error::other(format!(
            "{} 은(는) 정션 또는 심볼릭 링크입니다",
            item.path.display()
        )));
    }
    let mut sid = PSID::default();
    // SAFETY: the string is NUL-terminated; the SID is freed by `Local`.
    unsafe { ConvertStringSidToSidW(&HSTRING::from(owner), &mut sid) }?;
    let _free = Local(sid.0);
    // An ACL header (8 bytes) with no ACEs: never a NULL DACL, which would give everyone access.
    let mut acl = [0u32; 2];
    // SAFETY: the buffer is 8 bytes, aligned, and holds exactly the header.
    unsafe {
        InitializeAcl(
            acl.as_mut_ptr() as *mut ACL,
            size_of_val(&acl) as u32,
            ACL_REVISION,
        )
    }?;
    // SAFETY: the name is NUL-terminated; `sid` and `acl` live until the call returns.
    let err = unsafe {
        SetNamedSecurityInfoW(
            &HSTRING::from(item.path.as_path()),
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION
                | DACL_SECURITY_INFORMATION
                | UNPROTECTED_DACL_SECURITY_INFORMATION,
            Some(sid),
            None,
            Some(acl.as_ptr() as *const ACL),
            None,
        )
    };
    win32(err)
}

/// `Get-DataRootAclProblems`: what differs from the ACL `initialize_data_root` sets (empty:
/// exactly that), read back from the disk.
pub fn acl_problems(root: &Path, owner: &str, sids: &[String]) -> Vec<String> {
    let shown = root.display();
    match attributes(root) {
        Ok(a) if is_reparse(a) => return vec![format!("{shown}: 정션 또는 심볼릭 링크")],
        Ok(_) => {}
        Err(e) => return vec![format!("{shown}: 확인하지 못했습니다: {e}")],
    }
    let items = match tree_items(root) {
        Ok(items) => items,
        Err(e) => return vec![format!("{shown}: 확인하지 못했습니다: {e}")],
    };
    let root_item = Item {
        path: root.to_path_buf(),
        is_dir: true,
        reparse: false,
    };
    let mut problems = Vec::new();
    for (index, item) in std::iter::once(&root_item).chain(&items).enumerate() {
        let name = item.path.display();
        if item.reparse {
            problems.push(format!("{name}: 정션 또는 심볼릭 링크"));
            continue;
        }
        let sec = match read_security(&item.path) {
            Ok(sec) => sec,
            Err(e) => {
                problems.push(format!("{name}: 권한을 읽지 못했습니다: {e}"));
                continue;
            }
        };
        if !sec.owner.eq_ignore_ascii_case(owner) {
            problems.push(format!("{name}: 소유자 {}", sec.owner));
        }
        let explicit: Vec<&Ace> = sec
            .aces
            .iter()
            .filter(|a| a.flags & INHERITED_ACE == 0)
            .collect();
        if index == 0 {
            if !sec.protected {
                problems.push(format!("{name}: 상위 폴더의 권한을 상속함"));
            }
            let inherit = OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE;
            for sid in sids {
                let full = explicit.iter().any(|a| {
                    a.sid.eq_ignore_ascii_case(sid)
                        && a.allow
                        && a.mask & FULL_CONTROL == FULL_CONTROL
                        && a.flags & inherit == inherit
                        && a.flags & INHERIT_ONLY_ACE == 0
                });
                if !full {
                    problems.push(format!("{name}: {sid} 의 모든 권한 없음"));
                }
            }
        } else if !explicit.is_empty() {
            problems.push(format!("{name}: 자체 ACE {}개", explicit.len()));
        }
        for a in &sec.aces {
            if !a.allow || !contains_sid(sids, &a.sid) {
                let kind = if a.allow { "허용" } else { "거부" };
                problems.push(format!("{name}: {} {kind} {}", a.sid, rights_text(a.mask)));
            }
        }
    }
    problems
}

/// `Initialize-DataRoot`: creates or takes over the data root (finding C1).
pub fn initialize_data_root(
    root: &Path,
    owner: &str,
    sids: &[String],
    owners: &[String],
    created_by: &str,
) -> Result<(), String> {
    initialize_data_root_with(
        root,
        owner,
        sids,
        owners,
        created_by,
        &create_protected_dirs,
    )
}

/// The marker's `created_at`: now in KST, to the second (`2026-11-07T15:04:05+09:00`).
pub(crate) fn kst_now() -> String {
    let format = time::macros::format_description!(
        "[year]-[month]-[day]T[hour]:[minute]:[second][offset_hour sign:mandatory]:[offset_minute]"
    );
    time::OffsetDateTime::now_utc()
        .to_offset(time::macros::offset!(+9))
        .format(format)
        .expect("a fixed format always formats")
}

#[derive(serde::Serialize)]
struct Marker<'a> {
    product: &'a str,
    created_by: &'a str,
    created_at: String,
}

/// [`initialize_data_root`] with the creation step replaceable (tests). The order is
/// `Initialize-DataRoot`'s: the root's and its ancestors' checks; a missing root created with
/// its final ACL and read back as found (a folder another account made the moment before keeps
/// that account's owner and ACL: refused); the ancestors again; the root's checks again; the
/// root's ACL from scratch; the checks again now nobody else can write; every item below reset;
/// `logs`, `data`, `scripts` and the marker (only if missing); then the ACL read back.
pub fn initialize_data_root_with(
    root: &Path,
    owner: &str,
    sids: &[String],
    owners: &[String],
    created_by: &str,
    create: &dyn Fn(&Path, &RootSecurity) -> io::Result<()>,
) -> Result<(), String> {
    let shown = root.display();
    let sec = RootSecurity::new(owner, sids).map_err(|e| e.to_string())?;
    let check = || data_root_problem(root, owners);
    let check_ancestors = || ancestor_problem(root, owners, &read_security);
    if let Some(problem) = check().or_else(check_ancestors) {
        return Err(problem);
    }
    let missing = |p: &Path| matches!(attributes(p), Err(e) if e.kind() == io::ErrorKind::NotFound);
    if missing(root) {
        create(root, &sec).map_err(|e| format!("{shown} 을(를) 만들지 못했습니다: {e}"))?;
        let problems = acl_problems(root, owner, sids);
        if !problems.is_empty() {
            return Err(format!(
                "{shown} 을(를) 다른 계정이 먼저 만들었습니다: {}",
                problems.join("; ")
            ));
        }
        if let Some(problem) = check_ancestors() {
            return Err(problem);
        }
    }
    if let Some(problem) = check() {
        return Err(problem);
    }
    set_root_acl(root, &sec).map_err(|e| format!("{shown} 의 권한을 바꾸지 못했습니다: {e}"))?;
    if let Some(problem) = check() {
        return Err(problem);
    }
    let reset = |item: &Item| {
        reset_item_acl(item, owner).map_err(|e| {
            format!(
                "{} 의 권한을 다시 정하지 못했습니다: {e}",
                item.path.display()
            )
        })
    };
    let items = tree_items(root).map_err(|e| format!("{shown} 을(를) 확인하지 못했습니다: {e}"))?;
    for item in &items {
        reset(item)?;
    }
    for d in ["logs", "data", "scripts"] {
        let dir = root.join(d);
        if missing(&dir) {
            std::fs::create_dir(&dir)
                .map_err(|e| format!("{} 을(를) 만들지 못했습니다: {e}", dir.display()))?;
            reset(&Item {
                path: dir,
                is_dir: true,
                reparse: false,
            })?;
        } else if !attributes(&dir).is_ok_and(is_directory) {
            return Err(format!("{} 이(가) 폴더가 아닙니다", dir.display()));
        }
    }
    let marker = root.join("data").join("mcp-monitor-data-root.json");
    if missing(&marker) {
        let text = serde_json::to_string_pretty(&Marker {
            product: "mcp-monitor",
            created_by,
            created_at: kst_now(),
        })
        .map_err(|e| e.to_string())?;
        std::fs::write(&marker, text)
            .map_err(|e| format!("{} 을(를) 쓰지 못했습니다: {e}", marker.display()))?;
        reset(&Item {
            path: marker,
            is_dir: false,
            reparse: false,
        })?;
    }
    let problems = acl_problems(root, owner, sids);
    if !problems.is_empty() {
        return Err(format!(
            "데이터 폴더 권한 확인 실패: {}",
            problems.join("; ")
        ));
    }
    Ok(())
}

/// New (Y15, ruling E1, F16): why the install folder must not be used (`None`: safe). The
/// service runs its programs as SYSTEM, so `dir` and everything below it must be free of links,
/// owned by `owners` or TrustedInstaller, and give no other account `OPEN_RIGHTS`. Plan 5 only
/// warned.
pub fn install_tree_problem(dir: &Path, owners: &[String]) -> Option<String> {
    install_tree_problem_with(dir, owners, &read_security)
}

/// [`install_tree_problem`] with the ACL reads replaceable (tests: owners a standard account
/// cannot set on a real file).
pub fn install_tree_problem_with(
    dir: &Path,
    owners: &[String],
    read: &dyn Fn(&Path) -> io::Result<SecurityInfo>,
) -> Option<String> {
    const TAIL: &str = "서비스(SYSTEM)가 이 폴더의 프로그램을 실행하므로 설치할 수 없습니다";
    let shown = dir.display();
    let a = match attributes(dir) {
        Ok(a) => a,
        Err(e) => return Some(format!("{shown} 을(를) 확인하지 못했습니다: {e}")),
    };
    if !is_directory(a) {
        return Some(format!("{shown} 은(는) 폴더가 아닙니다. {TAIL}"));
    }
    if is_reparse(a) {
        return Some(format!(
            "{shown} 은(는) 정션 또는 심볼릭 링크입니다. {TAIL}"
        ));
    }
    let items = match tree_items(dir) {
        Ok(items) => items,
        Err(e) => return Some(format!("{shown} 을(를) 확인하지 못했습니다: {e}")),
    };
    let mut trusted = owners.to_vec();
    trusted.push(TRUSTED_INSTALLER.to_string());
    let root_item = Item {
        path: dir.to_path_buf(),
        is_dir: true,
        reparse: false,
    };
    for item in std::iter::once(&root_item).chain(&items) {
        let name = item.path.display();
        if item.reparse {
            return Some(format!("{name} 은(는) 정션 또는 심볼릭 링크입니다. {TAIL}"));
        }
        let sec = match read(&item.path) {
            Ok(sec) => sec,
            Err(e) => return Some(format!("{name} 을(를) 확인하지 못했습니다: {e}")),
        };
        if !contains_sid(&trusted, &sec.owner) {
            return Some(format!(
                "{name} 의 소유자({})가 관리자가 아닙니다. {TAIL}",
                sec.owner
            ));
        }
        if let Some(rule) = untrusted_rule(&sec.aces, owners, OPEN_RIGHTS) {
            return Some(format!(
                "{name}을(를) 관리자가 아닌 계정({})이 바꿀 수 있습니다({}). {TAIL}",
                rule.sid,
                rights_text(rule.mask)
            ));
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::paths::{Env, SystemVolumes, Volumes};
    use crate::install::testutil::*;
    use std::{
        fs, io,
        path::{Path, PathBuf},
    };

    fn ace(sid: &str, allow: bool, mask: u32, flags: u8) -> Ace {
        Ace {
            sid: sid.into(),
            allow,
            mask,
            flags,
        }
    }

    #[test]
    fn untrusted_rule_ignores_deny_inherit_only_placeholders_and_app_containers() {
        let owners = vec![SYSTEM.to_string(), ADMINISTRATORS.to_string()];
        let aces = vec![
            ace(AUTHENTICATED_USERS, false, GENERIC_ALL, 0),
            ace(
                AUTHENTICATED_USERS,
                true,
                FILE_DELETE_CHILD,
                INHERIT_ONLY_ACE,
            ),
            ace("S-1-3-0", true, GENERIC_ALL, 0),
            ace("S-1-15-2-1", true, GENERIC_ALL, 0),
            ace(TRUSTED_INSTALLER, true, GENERIC_ALL, 0),
            ace(ADMINISTRATORS, true, GENERIC_ALL, 0),
            ace(AUTHENTICATED_USERS, true, READ_EXECUTE, 0),
        ];
        assert_eq!(untrusted_rule(&aces, &owners, OPEN_RIGHTS), None);
        let mut inherited = aces.clone();
        inherited.push(ace(AUTHENTICATED_USERS, true, GENERIC_ALL, INHERITED_ACE));
        assert_eq!(
            untrusted_rule(&inherited, &owners, OPEN_RIGHTS).map(|a| a.sid.as_str()),
            Some(AUTHENTICATED_USERS)
        );
        let delete_only = vec![ace(AUTHENTICATED_USERS, true, DELETE, 0)];
        assert!(untrusted_rule(&delete_only, &owners, ANCESTOR_RIGHTS).is_some());
        assert!(untrusted_rule(&delete_only, &owners, ANCESTOR_RIGHTS & !DELETE).is_none());
    }

    #[test]
    fn data_root_problem_names_a_foreign_owner() {
        let s = Scratch::new();
        let root = s.path().join("r");
        fs::create_dir_all(root.join("data")).unwrap();
        fs::write(root.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        assert_eq!(data_root_problem(&root, &owners()), None);
        let p =
            data_root_problem(&root, &[SYSTEM.to_string(), ADMINISTRATORS.to_string()]).unwrap();
        assert!(p.contains(&me()) && p.contains("소유자"), "{p}");
        assert_eq!(data_root_problem(&s.path().join("missing"), &[]), None);
    }

    #[test]
    fn a_data_root_someone_else_filled_is_refused_and_an_empty_or_earlier_one_accepted() {
        let s = Scratch::new();
        let p = s.path();
        let foreign = p.join("foreign");
        fs::create_dir_all(foreign.join("scripts")).unwrap();
        fs::write(foreign.join("scripts/a.ps1"), "x").unwrap();
        let linked = p.join("linked");
        fs::create_dir_all(linked.join("data")).unwrap();
        fs::write(linked.join("data/install-state.json"), "{}").unwrap();
        junction(&linked.join("scripts"), &p.join("elsewhere"));
        let deep = p.join("deep");
        fs::create_dir_all(deep.join("data")).unwrap();
        fs::write(deep.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        fs::create_dir_all(deep.join("logs/x")).unwrap();
        junction(&deep.join("logs/x/y"), &p.join("elsewhere2"));
        let root_link = p.join("rootlink");
        junction(&root_link, &p.join("target"));
        let a_file = p.join("file");
        fs::write(&a_file, "x").unwrap();
        for (name, root) in [
            ("not empty", &foreign),
            ("junction inside", &linked),
            ("deep junction", &deep),
            ("root is a junction", &root_link),
            ("a file", &a_file),
        ] {
            assert!(data_root_problem(root, &owners()).is_some(), "{name}");
        }
        let empty = p.join("empty");
        fs::create_dir(&empty).unwrap();
        let earlier = p.join("earlier");
        fs::create_dir_all(earlier.join("logs")).unwrap();
        fs::write(earlier.join("logs/2026-11-01.jsonl"), "{}\n").unwrap();
        fs::create_dir_all(earlier.join("data")).unwrap();
        fs::write(earlier.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        for root in [&empty, &earlier, &p.join("missing")] {
            assert_eq!(data_root_problem(root, &owners()), None, "{root:?}");
        }
    }

    #[test]
    fn initialize_data_root_rebuilds_the_acl_from_scratch() {
        let s = Scratch::new();
        let root = s.path().join("MCP Monitor");
        fs::create_dir_all(root.join("data")).unwrap();
        fs::write(root.join("data/install-state.json"), "{}").unwrap();
        let log = root.join("logs/2026-11-01.jsonl");
        fs::create_dir_all(log.parent().unwrap()).unwrap();
        fs::write(&log, "{}\n").unwrap();
        icacls(&root, &["/grant", &format!("*{EVERYONE}:(OI)(CI)RX")]);
        icacls(&log, &["/grant", &format!("*{EVERYONE}:R")]);
        assert!(sddl(&root).contains(";;;WD)") && sddl(&log).contains(";;;WD)"));
        let (me, sids) = (me(), owners());
        initialize_data_root(&root, &me, &sids, &sids, "install").unwrap();
        assert_eq!(acl_problems(&root, &me, &sids), Vec::<String>::new());
        icacls(&log, &["/grant", &format!("*{EVERYONE}:R")]);
        let problems = acl_problems(&root, &me, &sids).join("|");
        assert!(
            problems.contains(EVERYONE) && problems.contains("2026-11-01.jsonl"),
            "{problems}"
        );
        icacls(&log, &["/remove", &format!("*{EVERYONE}")]);
        for item in walk_all(&root) {
            let d = sddl(&item);
            assert!(
                !d.contains("WD)") && d.starts_with(&format!("O:{me}")),
                "{item:?} {d}"
            );
        }
        assert!(sddl(&root).contains("D:P"));
        for d in ["logs", "data", "scripts"] {
            assert!(root.join(d).is_dir(), "{d}");
        }
        let marker: serde_json::Value = serde_json::from_str(
            &fs::read_to_string(root.join("data/mcp-monitor-data-root.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(
            (marker["product"].as_str(), marker["created_by"].as_str()),
            (Some("mcp-monitor"), Some("install"))
        );
    }

    #[test]
    fn initialize_data_root_creates_a_new_root_and_its_missing_parent() {
        let s = Scratch::new();
        let root = s.path().join("new").join("MCP Monitor");
        let (me, sids) = (me(), owners());
        initialize_data_root(&root, &me, &sids, &sids, "audit-policy").unwrap();
        assert!(acl_problems(&root, &me, &sids).is_empty());
        let mut names: Vec<String> = fs::read_dir(&root)
            .unwrap()
            .map(|e| e.unwrap().file_name().into_string().unwrap())
            .collect();
        names.sort();
        assert_eq!(names, ["data", "logs", "scripts"]);
        for folder in [s.path().join("new"), root.clone()] {
            let d = sddl(&folder);
            assert!(
                d.starts_with(&format!("O:{me}"))
                    && d.contains("D:P")
                    && !d.contains("WD)")
                    && !d.contains("AU)"),
                "{folder:?} {d}"
            );
        }
        // Addition: the marker says who made it and when, in KST to the second.
        let marker: serde_json::Value = serde_json::from_str(
            &fs::read_to_string(root.join("data/mcp-monitor-data-root.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(marker["created_by"].as_str(), Some("audit-policy"));
        let at = marker["created_at"].as_str().unwrap();
        assert!(
            regex::Regex::new(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+09:00$")
                .unwrap()
                .is_match(at),
            "{at}"
        );
    }

    #[test]
    fn initialize_data_root_refuses_a_foreign_folder_and_changes_nothing() {
        let s = Scratch::new();
        let root = s.path().join("r");
        fs::create_dir_all(root.join("scripts")).unwrap();
        let before = sddl(&root);
        let sids = owners();
        let err = initialize_data_root(&root, &me(), &sids, &sids, "install").unwrap_err();
        assert!(err.contains("MCP Monitor"), "{err}");
        assert_eq!(sddl(&root), before);
        assert!(!root.join("data").exists());
    }

    #[test]
    fn initialize_data_root_refuses_a_root_made_just_before_it() {
        let s = Scratch::new();
        let root = s.path().join("MCP Monitor");
        let sids = owners();
        let attacker = |p: &Path, sd: &RootSecurity| -> io::Result<()> {
            fs::create_dir_all(p)?; // another account wins the race: the folder inherits its parent's ACL
            create_protected_dirs(p, sd)
        };
        let err = initialize_data_root_with(&root, &me(), &sids, &sids, "install", &attacker)
            .unwrap_err();
        assert!(err.contains("먼저 만들었습니다"), "{err}");
        assert!(!sddl(&root).contains("D:P") && !root.join("data").exists());
    }

    #[test]
    fn a_data_root_below_a_folder_others_may_rename_is_refused() {
        let s = Scratch::new();
        let apps = s.path().join("apps");
        fs::create_dir(&apps).unwrap();
        let root = apps.join("MCP Monitor");
        grant(&apps, "(OI)(CI)M");
        let p = ancestor_problem(&root, &owners(), &read_security).unwrap();
        assert!(
            p.contains(&apps.display().to_string()) && p.contains(AUTHENTICATED_USERS),
            "{p}"
        );
        icacls(&apps, &["/remove:g", &format!("*{AUTHENTICATED_USERS}")]);
        grant(&apps, "(OI)(CI)(IO)M");
        assert_eq!(ancestor_problem(&root, &owners(), &read_security), None);
    }

    #[test]
    fn ancestor_check_passes_the_default_and_drive_level_roots() {
        let e = Env::from_process();
        let o = vec![SYSTEM.to_string(), ADMINISTRATORS.to_string()];
        assert_eq!(
            ancestor_problem(
                &PathBuf::from(e.get("ProgramData").unwrap()).join("MCP Monitor"),
                &o,
                &read_security
            ),
            None
        );
        for l in SystemVolumes.local_fixed_letters() {
            assert_eq!(
                ancestor_problem(Path::new(&format!("{l}:\\MCP Monitor")), &o, &read_security),
                None,
                "{l}"
            );
        }
    }

    #[test]
    fn ancestor_check_includes_the_drive_root() {
        for (g, refused) in [
            ("(DC)", true),
            ("(WDAC)", true),
            ("(WO)", true),
            ("F", true),
            ("M", false),
            ("(AD)", false),
            ("(OI)(CI)(IO)M", false),
        ] {
            let s = Scratch::new();
            let fake = s.path().join("fake-drive-root");
            fs::create_dir(&fake).unwrap();
            grant(&fake, g);
            let drive = PathBuf::from(&s.path().display().to_string()[..3]);
            let acl = |p: &Path| {
                if p == drive {
                    read_security(&fake)
                } else {
                    read_security(p)
                }
            };
            let r = ancestor_problem(&s.path().join("MCP Monitor"), &owners(), &acl);
            if refused {
                let r = r.unwrap_or_else(|| panic!("{g} was accepted"));
                assert!(
                    r.contains(&drive.display().to_string())
                        && r.contains(AUTHENTICATED_USERS)
                        && r.contains("드라이브"),
                    "{g}: {r}"
                );
            } else {
                assert_eq!(r, None, "{g}");
            }
        }
    }

    #[test]
    fn an_existing_data_root_others_may_delete_or_rechmod_is_refused() {
        for case in [
            "inherited_modify",
            "write_dac",
            "write_owner",
            "delete_on_a_file",
            "write_on_a_script",
        ] {
            let s = Scratch::new();
            let root = if case == "inherited_modify" {
                let vol = s.path().join("vol");
                fs::create_dir(&vol).unwrap();
                grant(&vol, "(OI)(CI)(IO)M");
                let r = vol.join("MCP Monitor");
                fs::create_dir(&r).unwrap();
                r
            } else {
                let r = s.path().join("MCP Monitor");
                fs::create_dir_all(r.join("data")).unwrap();
                fs::write(r.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
                fs::write(r.join("data/config.db"), b"").unwrap();
                fs::create_dir(r.join("scripts")).unwrap();
                fs::write(r.join("scripts/a.ps1"), "x").unwrap();
                let (target, g) = match case {
                    "write_dac" => (r.clone(), "(WDAC)"),
                    "write_owner" => (r.clone(), "(WO)"),
                    "delete_on_a_file" => (r.join("data/config.db"), "(D)"),
                    _ => (r.join("scripts/a.ps1"), "(WD)"),
                };
                grant(&target, g);
                r
            };
            let before = sddl(&root);
            let p = data_root_problem(&root, &owners())
                .unwrap_or_else(|| panic!("{case} was accepted"));
            assert!(
                p.contains(AUTHENTICATED_USERS) && p.contains("지우고"),
                "{case}: {p}"
            );
            let sids = owners();
            let err = initialize_data_root(&root, &me(), &sids, &sids, "install").unwrap_err();
            assert!(err.contains(AUTHENTICATED_USERS), "{case}: {err}");
            assert_eq!(sddl(&root), before, "{case}");
            assert!(!before.contains("D:P"));
        }
    }

    #[test]
    fn an_existing_data_root_with_harmless_extra_rights_is_accepted() {
        let s = Scratch::new();
        let root = s.path().join("MCP Monitor");
        fs::create_dir(&root).unwrap();
        grant(&root, "(OI)(CI)RX");
        icacls(&root, &["/grant", &format!("*{EVERYONE}:(OI)(CI)(IO)RX")]);
        assert_eq!(data_root_problem(&root, &owners()), None);
    }

    #[test]
    fn data_root_problem_looks_again_when_a_file_goes_away() {
        let s = Scratch::new();
        let root = s.path().join("r");
        fs::create_dir(&root).unwrap();
        let mut walks = 0;
        let mut first_fails = |_: &Path| -> io::Result<Vec<Item>> {
            walks += 1;
            if walks == 1 {
                Err(io::Error::from(io::ErrorKind::NotFound))
            } else {
                Ok(vec![])
            }
        };
        assert_eq!(
            data_root_problem_with(&root, &owners(), &mut first_fails),
            None
        );
        assert_eq!(walks, 2);
        let mut always_walks = 0;
        let mut always = |_: &Path| -> io::Result<Vec<Item>> {
            always_walks += 1;
            Err(io::Error::from(io::ErrorKind::NotFound))
        };
        assert!(
            data_root_problem_with(&root, &owners(), &mut always)
                .unwrap()
                .contains("확인하지 못했습니다")
        );
        // Addition: exactly one more look, as in Plan 5 (walks 2, not more).
        assert_eq!(always_walks, 2);
        // Addition (F30): an item whose ACL cannot be read because it went away counts the same.
        let gone = Item {
            path: root.join("gone.jsonl"),
            is_dir: false,
            reparse: false,
        };
        let mut lists_a_missing_file =
            |_: &Path| -> io::Result<Vec<Item>> { Ok(vec![gone.clone()]) };
        let p = data_root_problem_with(&root, &owners(), &mut lists_a_missing_file).unwrap();
        assert!(p.contains("확인하지 못했습니다"), "{p}");
    }

    #[test]
    fn a_locked_data_root_is_unreadable_without_admin() {
        let s = Scratch::new();
        let root = s.path().join("MCP Monitor");
        fs::create_dir_all(root.join("data")).unwrap();
        assert!(data_root_readable(&root));
        icacls(
            &root,
            &[
                "/inheritance:r",
                "/grant:r",
                "*S-1-5-18:(OI)(CI)F",
                "*S-1-5-32-544:(OI)(CI)F",
            ],
        );
        assert!(!data_root_readable(&root));
        icacls(&root, &["/reset", "/T", "/C", "/Q"]);
    }

    #[test]
    fn an_install_tree_others_may_write_is_refused() {
        let s = Scratch::new();
        let i = s.path().join("i");
        fs::create_dir_all(i.join("bin/monitor")).unwrap();
        fs::write(i.join("bin/monitor/mcp-monitor-server.exe"), b"x").unwrap();
        assert_eq!(install_tree_problem(&i, &owners()), None);
        grant(&i.join("bin/monitor/mcp-monitor-server.exe"), "(W)");
        let p = install_tree_problem(&i, &owners()).unwrap();
        assert!(
            p.contains("mcp-monitor-server.exe") && p.contains(AUTHENTICATED_USERS),
            "{p}"
        );
    }

    // --- additions beyond the plan's list ---------------------------------------------------

    #[test]
    fn an_install_tree_with_a_link_or_a_foreign_owner_is_refused() {
        // F16: an owner outside SYSTEM/Administrators/TrustedInstaller can rewrite the DACL at will.
        let s = Scratch::new();
        let i = s.path().join("i");
        fs::create_dir_all(i.join("web")).unwrap();
        fs::write(i.join("web/index.html"), "x").unwrap();
        let admins = vec![SYSTEM.to_string(), ADMINISTRATORS.to_string()];
        let as_owned_by = |owner: &'static str, item: &'static str| {
            move |p: &Path| -> io::Result<SecurityInfo> {
                let mut sec = read_security(p)?;
                if p.ends_with(item) {
                    sec.owner = owner.to_string();
                }
                // Only admins (and this account's ACE, renamed to Administrators) are on the DACL.
                for a in &mut sec.aces {
                    if a.sid == me() {
                        a.sid = ADMINISTRATORS.to_string();
                    }
                }
                if !p.ends_with(item) {
                    sec.owner = ADMINISTRATORS.to_string();
                }
                Ok(sec)
            }
        };
        let foreign = "S-1-5-21-1-2-3-1001";
        let p =
            install_tree_problem_with(&i, &admins, &as_owned_by(foreign, "index.html")).unwrap();
        assert!(
            p.contains("index.html") && p.contains(foreign) && p.contains("소유자"),
            "{p}"
        );
        assert_eq!(
            install_tree_problem_with(&i, &admins, &as_owned_by(TRUSTED_INSTALLER, "index.html")),
            None
        );
        let p = install_tree_problem_with(&i, &admins, &as_owned_by(foreign, "i")).unwrap();
        assert!(p.contains(foreign), "{p}");
        junction(&i.join("web/link"), &s.path().join("elsewhere"));
        let p = install_tree_problem(&i, &owners()).unwrap();
        assert!(
            p.contains("link") && p.contains("정션 또는 심볼릭 링크"),
            "{p}"
        );
        assert!(install_tree_problem(&s.path().join("missing"), &owners()).is_some());
    }

    #[test]
    fn read_security_maps_other_ace_types_and_a_null_dacl_to_full_access() {
        // An object ACE and a callback ACE: neither is a plain allow or deny, so both count as an
        // allow of GENERIC_ALL (stricter than .NET, which skips them; F30), keeping their flags.
        let sec = security_from_sddl(
            "O:SYD:P(A;OICI;FA;;;SY)(D;;FA;;;WD)(OA;CI;GA;bf967aba-0de6-11d0-a285-00aa003049e2;;AU)",
        )
        .unwrap();
        assert_eq!(sec.owner, SYSTEM);
        assert!(sec.protected);
        assert_eq!(sec.aces[0], ace(SYSTEM, true, 0x1F01FF, 0x3));
        assert_eq!(sec.aces[1], ace(EVERYONE, false, 0x1F01FF, 0));
        assert!(sec.aces[2].allow && sec.aces[2].mask == GENERIC_ALL && sec.aces[2].flags == 0x2);
        assert!(untrusted_rule(&sec.aces, &[SYSTEM.to_string()], OPEN_RIGHTS).is_some());
        let null_dacl = security_from_sddl("O:BAD:NO_ACCESS_CONTROL").unwrap();
        assert_eq!(null_dacl.owner, ADMINISTRATORS);
        assert_eq!(null_dacl.aces, [ace(EVERYONE, true, GENERIC_ALL, 0)]);
        let empty = security_from_sddl("O:BAD:P").unwrap();
        assert!(empty.aces.is_empty() && empty.protected);
    }

    #[test]
    fn sddl_of_matches_powershell_and_read_security_matches_sddl() {
        let s = Scratch::new();
        let f = s.path().join("f.txt");
        fs::write(&f, "x").unwrap();
        grant(&f, "(WD)");
        let out = std::process::Command::new(crate::winutil::system_tool(
            r"WindowsPowerShell\v1.0\powershell.exe",
        ))
        .args(["-NoProfile", "-NonInteractive", "-Command"])
        .arg(format!(
            "(Get-Acl -LiteralPath '{}').GetSecurityDescriptorSddlForm('Owner, Access')",
            f.display()
        ))
        .output()
        .unwrap();
        assert!(out.status.success());
        assert_eq!(sddl(&f), String::from_utf8_lossy(&out.stdout).trim());
        let sec = read_security(&f).unwrap();
        assert_eq!(sec.owner, me());
        assert!(!sec.protected);
        let au = sec
            .aces
            .iter()
            .find(|a| a.sid == AUTHENTICATED_USERS)
            .unwrap();
        assert!(au.allow && au.flags & INHERITED_ACE == 0 && au.mask & FILE_WRITE_DATA != 0);
        assert!(
            sec.aces
                .iter()
                .any(|a| a.sid == SYSTEM && a.flags & INHERITED_ACE != 0)
        );
        assert_eq!(
            read_security(&s.path().join("missing")).unwrap_err().kind(),
            io::ErrorKind::NotFound
        );
    }

    #[test]
    fn tree_items_lists_links_without_entering_them() {
        let s = Scratch::new();
        let r = s.path().join("r");
        fs::create_dir_all(r.join("a/b")).unwrap();
        fs::write(r.join("a/b/f"), "x").unwrap();
        fs::create_dir_all(s.path().join("outside/deeper")).unwrap();
        junction(&r.join("a/link"), &s.path().join("outside"));
        let mut items = tree_items(&r).unwrap();
        items.sort_by(|x, y| x.path.cmp(&y.path));
        let got: Vec<(String, bool, bool)> = items
            .iter()
            .map(|i| {
                (
                    i.path.strip_prefix(&r).unwrap().display().to_string(),
                    i.is_dir,
                    i.reparse,
                )
            })
            .collect();
        assert_eq!(
            got,
            [
                ("a".to_string(), true, false),
                (r"a\b".to_string(), true, false),
                (r"a\b\f".to_string(), false, false),
                (r"a\link".to_string(), true, true),
            ]
        );
        assert_eq!(
            tree_items(&s.path().join("missing")).unwrap_err().kind(),
            io::ErrorKind::NotFound
        );
    }

    #[test]
    fn reset_item_acl_refuses_a_link_and_drops_explicit_aces() {
        let s = Scratch::new();
        let link = s.path().join("link");
        junction(&link, &s.path().join("real"));
        let item = Item {
            path: link.clone(),
            is_dir: true,
            reparse: false, // the flag is stale: the item is looked at again
        };
        let e = reset_item_acl(&item, &me()).unwrap_err();
        assert!(e.to_string().contains("정션 또는 심볼릭 링크"), "{e}");
        let f = s.path().join("f");
        fs::write(&f, "x").unwrap();
        grant(&f, "(W)");
        let file = Item {
            path: f.clone(),
            is_dir: false,
            reparse: false,
        };
        reset_item_acl(&file, &me()).unwrap();
        let sec = read_security(&f).unwrap();
        assert!(
            sec.aces.iter().all(|a| a.flags & INHERITED_ACE != 0),
            "{sec:?}"
        );
        assert!(!sec.aces.is_empty());
    }

    #[test]
    fn root_security_takes_only_sids() {
        assert!(RootSecurity::new(&me(), &owners()).is_ok());
        for bad in ["S-1-5-18)(A;OICI;FA;;;WD", "WD", "", "S-1-5-18 "] {
            assert!(
                RootSecurity::new(&me(), &[bad.to_string()]).is_err(),
                "{bad}"
            );
            assert!(RootSecurity::new(bad, &owners()).is_err(), "{bad}");
        }
        let sec = RootSecurity::new(ADMINISTRATORS, &[SYSTEM.to_string()]).unwrap();
        assert_eq!(
            sec.sddl(),
            format!("O:{ADMINISTRATORS}D:P(A;OICI;FA;;;{SYSTEM})")
        );
    }

    #[test]
    fn an_existing_marker_is_kept() {
        let s = Scratch::new();
        let root = s.path().join("MCP Monitor");
        fs::create_dir_all(root.join("data")).unwrap();
        let text = r#"{"product":"mcp-monitor","created_by":"install","created_at":"2026-11-01T09:00:00+09:00"}"#;
        fs::write(root.join("data/mcp-monitor-data-root.json"), text).unwrap();
        let (me, sids) = (me(), owners());
        initialize_data_root(&root, &me, &sids, &sids, "audit-policy").unwrap();
        assert_eq!(
            fs::read_to_string(root.join("data/mcp-monitor-data-root.json")).unwrap(),
            text
        );
        // Initializing again over its own result is accepted and changes nothing that matters.
        initialize_data_root(&root, &me, &sids, &sids, "install").unwrap();
        assert!(acl_problems(&root, &me, &sids).is_empty());
    }

    #[test]
    fn every_acl_guard_ignores_path_case() {
        // F04: the drive root is found whatever case the data root is written in, and the data
        // root guards work on a path written in the other case.
        let s = Scratch::new();
        let fake = s.path().join("fake-drive-root");
        fs::create_dir(&fake).unwrap();
        grant(&fake, "(DC)");
        let lower_root = PathBuf::from(swap_case(&s.path().join("MCP Monitor")));
        let acl = |p: &Path| {
            if same_path(p, Path::new(&s.path().display().to_string()[..3])) {
                read_security(&fake)
            } else {
                read_security(p)
            }
        };
        let r = ancestor_problem(&lower_root, &owners(), &acl).unwrap();
        assert!(
            r.contains("드라이브 루트") && r.contains(AUTHENTICATED_USERS),
            "{r}"
        );
        assert_eq!(
            ancestor_problem(&lower_root, &owners(), &read_security),
            None
        );

        let (me, sids) = (me(), owners());
        initialize_data_root(&lower_root, &me, &sids, &sids, "install").unwrap();
        let upper_root = s.path().join("MCP Monitor");
        assert!(acl_problems(&upper_root, &me, &sids).is_empty());
        assert!(acl_problems(&lower_root, &me, &sids).is_empty());
        assert_eq!(data_root_problem(&upper_root, &owners()), None);
        assert!(sddl(&upper_root).contains("D:P"));

        let i = s.path().join("Install");
        fs::create_dir_all(i.join("Bin")).unwrap();
        fs::write(i.join("Bin/Server.exe"), b"x").unwrap();
        grant(&i.join("Bin/Server.exe"), "(W)");
        let p = install_tree_problem(Path::new(&swap_case(&i)), &owners()).unwrap();
        assert!(p.contains(AUTHENTICATED_USERS), "{p}");
    }

    #[test]
    fn untrusted_rule_compares_sids_ignoring_case() {
        let owners = vec!["s-1-5-18".to_string()];
        let aces = vec![
            ace(SYSTEM, true, GENERIC_ALL, 0),
            ace("s-1-15-2-1", true, GENERIC_ALL, 0),
            ace("s-1-3-4", true, GENERIC_ALL, 0),
            ace(&TRUSTED_INSTALLER.to_lowercase(), true, GENERIC_ALL, 0),
        ];
        assert_eq!(untrusted_rule(&aces, &owners, OPEN_RIGHTS), None);
    }

    #[test]
    fn rights_are_named_in_messages() {
        assert_eq!(
            rights_text(0x1301BF),
            "DELETE, FILE_WRITE_DATA, FILE_APPEND_DATA (0x001301BF)"
        );
        assert_eq!(rights_text(GENERIC_ALL), "GENERIC_ALL (0x10000000)");
        assert_eq!(rights_text(READ_EXECUTE), "0x001200A9");
    }
}
