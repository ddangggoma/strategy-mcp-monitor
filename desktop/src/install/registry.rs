//! Registry writes of the installer (the Apps & features entry, Y19), the uninstaller (Task 8) and
//! `autostart` (Task 12) behind one trait: [`WinRegistry`] writes the real registry (64-bit view),
//! tests use [`FakeRegistry`] and never touch it (Y23). Keys are written with their hive prefix:
//! `HKLM\…`, `HKU\…` or `HKCU\…`.

use std::ffi::c_void;
use windows::Win32::Foundation::{
    ERROR_FILE_NOT_FOUND, ERROR_NO_MORE_ITEMS, ERROR_SUCCESS, WIN32_ERROR,
};
use windows::Win32::System::Registry::{
    HKEY, HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE, HKEY_USERS, KEY_ALL_ACCESS,
    KEY_ENUMERATE_SUB_KEYS, KEY_SET_VALUE, KEY_WOW64_64KEY, REG_DWORD, REG_OPTION_NON_VOLATILE,
    REG_SAM_FLAGS, REG_SZ, RRF_RT_REG_SZ, RRF_SUBKEY_WOW6464KEY, RegCloseKey, RegCreateKeyExW,
    RegDeleteTreeW, RegDeleteValueW, RegEnumKeyExW, RegGetValueW, RegOpenKeyExW, RegSetValueExW,
};
use windows::core::{HSTRING, PCWSTR, PWSTR};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RegValue {
    Sz(String),
    Dword(u32),
}

/// One `(registry-set)` argument: `Name=REG_SZ:text` or `Name=REG_DWORD:<u32>` (decimal ASCII
/// digits). The text may hold any character, `=` included.
pub fn parse_reg_value(s: &str) -> Result<(String, RegValue), String> {
    let bad =
        || format!("레지스트리 값 형식이 아닙니다(이름=REG_SZ:문자열 | 이름=REG_DWORD:숫자): {s}");
    let (name, typed) = s.split_once('=').ok_or_else(bad)?;
    if name.is_empty() {
        return Err(bad());
    }
    if let Some(text) = typed.strip_prefix("REG_SZ:") {
        return Ok((name.to_string(), RegValue::Sz(text.to_string())));
    }
    let digits = typed.strip_prefix("REG_DWORD:").ok_or_else(bad)?;
    if digits.is_empty() || digits.len() > 10 || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return Err(bad());
    }
    let n = digits.parse::<u32>().map_err(|_| bad())?;
    Ok((name.to_string(), RegValue::Dword(n)))
}

pub trait Registry {
    /// Creates `key` if needed and sets the values.
    fn set_values(&mut self, key: &str, values: &[(String, RegValue)]) -> Result<(), String>;
    /// Removes `key` with everything below it; a missing key is fine.
    fn delete_key(&mut self, key: &str) -> Result<(), String>;
    /// Removes one value; a missing key or value is fine.
    fn delete_value(&mut self, key: &str, name: &str) -> Result<(), String>;
    /// A `REG_SZ` value (`None`: missing or another type).
    fn string(&self, key: &str, name: &str) -> Option<String>;
    /// The names of the keys directly below `key` (empty when it is missing).
    fn subkeys(&self, key: &str) -> Vec<String>;
}

impl<T: Registry + ?Sized> Registry for &mut T {
    fn set_values(&mut self, key: &str, values: &[(String, RegValue)]) -> Result<(), String> {
        (**self).set_values(key, values)
    }
    fn delete_key(&mut self, key: &str) -> Result<(), String> {
        (**self).delete_key(key)
    }
    fn delete_value(&mut self, key: &str, name: &str) -> Result<(), String> {
        (**self).delete_value(key, name)
    }
    fn string(&self, key: &str, name: &str) -> Option<String> {
        (**self).string(key, name)
    }
    fn subkeys(&self, key: &str) -> Vec<String> {
        (**self).subkeys(key)
    }
}

/// The real registry, always the 64-bit view.
pub struct WinRegistry;

/// `HKLM\a\b` → (HKEY_LOCAL_MACHINE, `a\b`); a hive alone gives an empty sub key.
fn split_key(key: &str) -> Result<(HKEY, &str), String> {
    let (hive, rest) = key.split_once('\\').unwrap_or((key, ""));
    let root = match hive.to_ascii_uppercase().as_str() {
        "HKLM" => HKEY_LOCAL_MACHINE,
        "HKU" => HKEY_USERS,
        "HKCU" => HKEY_CURRENT_USER,
        _ => {
            return Err(format!(
                "레지스트리 키는 HKLM\\, HKU\\, HKCU\\ 로 시작해야 합니다: {key}"
            ));
        }
    };
    Ok((root, rest))
}

/// An open key, closed when dropped.
struct Key(HKEY);

impl Drop for Key {
    fn drop(&mut self) {
        // SAFETY: the key was opened by us and is closed once.
        let _ = unsafe { RegCloseKey(self.0) };
    }
}

fn check(err: WIN32_ERROR, what: &str, key: &str) -> Result<(), String> {
    if err == ERROR_SUCCESS {
        Ok(())
    } else {
        Err(format!(
            "{key} {what} 실패: {}",
            windows::core::Error::from_hresult(err.to_hresult()).message()
        ))
    }
}

/// Opens `sub` below `root` with `access` in the 64-bit view.
fn open(root: HKEY, sub: &str, access: REG_SAM_FLAGS) -> Result<Key, WIN32_ERROR> {
    let mut key = HKEY::default();
    // SAFETY: the name is NUL-terminated and outlives the call; `key` is a valid out pointer.
    let err = unsafe {
        RegOpenKeyExW(
            root,
            &HSTRING::from(sub),
            None,
            access | KEY_WOW64_64KEY,
            &mut key,
        )
    };
    if err == ERROR_SUCCESS {
        Ok(Key(key))
    } else {
        Err(err)
    }
}

impl Registry for WinRegistry {
    fn set_values(&mut self, key: &str, values: &[(String, RegValue)]) -> Result<(), String> {
        let (root, sub) = split_key(key)?;
        let mut handle = HKEY::default();
        // SAFETY: the strings are NUL-terminated and outlive the call; `handle` is a valid out pointer.
        let err = unsafe {
            RegCreateKeyExW(
                root,
                &HSTRING::from(sub),
                None,
                PCWSTR::null(),
                REG_OPTION_NON_VOLATILE,
                KEY_SET_VALUE | KEY_WOW64_64KEY,
                None,
                &mut handle,
                None,
            )
        };
        check(err, "만들기", key)?;
        let handle = Key(handle);
        for (name, value) in values {
            let (kind, bytes): (_, Vec<u8>) = match value {
                RegValue::Sz(text) => (
                    REG_SZ,
                    text.encode_utf16()
                        .chain([0])
                        .flat_map(u16::to_le_bytes)
                        .collect(),
                ),
                RegValue::Dword(n) => (REG_DWORD, n.to_le_bytes().to_vec()),
            };
            // SAFETY: an open key; the name is NUL-terminated; the data slice is valid.
            let err = unsafe {
                RegSetValueExW(
                    handle.0,
                    &HSTRING::from(name.as_str()),
                    None,
                    kind,
                    Some(&bytes),
                )
            };
            check(err, &format!("값 {name} 쓰기"), key)?;
        }
        Ok(())
    }

    fn delete_key(&mut self, key: &str) -> Result<(), String> {
        let (root, sub) = split_key(key)?;
        if sub.is_empty() {
            return Err(format!("하이브 전체는 지울 수 없습니다: {key}"));
        }
        let (parent, leaf) = sub.rsplit_once('\\').unwrap_or(("", sub));
        let parent = match open(root, parent, KEY_ALL_ACCESS) {
            Ok(k) => k,
            Err(e) if e == ERROR_FILE_NOT_FOUND => return Ok(()),
            Err(e) => return check(e, "열기", key),
        };
        // SAFETY: an open key and a NUL-terminated sub key name.
        let err = unsafe { RegDeleteTreeW(parent.0, &HSTRING::from(leaf)) };
        if err == ERROR_FILE_NOT_FOUND {
            return Ok(());
        }
        check(err, "지우기", key)
    }

    fn delete_value(&mut self, key: &str, name: &str) -> Result<(), String> {
        let (root, sub) = split_key(key)?;
        let k = match open(root, sub, KEY_SET_VALUE) {
            Ok(k) => k,
            Err(e) if e == ERROR_FILE_NOT_FOUND => return Ok(()),
            Err(e) => return check(e, "열기", key),
        };
        // SAFETY: an open key and a NUL-terminated value name.
        let err = unsafe { RegDeleteValueW(k.0, &HSTRING::from(name)) };
        if err == ERROR_FILE_NOT_FOUND {
            return Ok(());
        }
        check(err, &format!("값 {name} 지우기"), key)
    }

    fn string(&self, key: &str, name: &str) -> Option<String> {
        let (root, sub) = split_key(key).ok()?;
        let (sub, name) = (HSTRING::from(sub), HSTRING::from(name));
        let flags = RRF_RT_REG_SZ | RRF_SUBKEY_WOW6464KEY;
        let mut size = 0u32;
        // SAFETY: a size query with no buffer.
        let err = unsafe { RegGetValueW(root, &sub, &name, flags, None, None, Some(&mut size)) };
        if err != ERROR_SUCCESS {
            return None;
        }
        let mut buf = vec![0u16; (size as usize).div_ceil(2)];
        // SAFETY: the buffer holds `size` bytes.
        let err = unsafe {
            RegGetValueW(
                root,
                &sub,
                &name,
                flags,
                None,
                Some(buf.as_mut_ptr() as *mut c_void),
                Some(&mut size),
            )
        };
        if err != ERROR_SUCCESS {
            return None;
        }
        let end = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
        Some(String::from_utf16_lossy(&buf[..end]))
    }

    fn subkeys(&self, key: &str) -> Vec<String> {
        let Ok((root, sub)) = split_key(key) else {
            return Vec::new();
        };
        let Ok(k) = open(root, sub, KEY_ENUMERATE_SUB_KEYS) else {
            return Vec::new();
        };
        let mut names = Vec::new();
        for index in 0.. {
            // A key name has at most 255 characters.
            let mut buf = [0u16; 256];
            let mut len = buf.len() as u32;
            // SAFETY: an open key; the buffer holds `len` UTF-16 units.
            let err = unsafe {
                RegEnumKeyExW(
                    k.0,
                    index,
                    Some(PWSTR(buf.as_mut_ptr())),
                    &mut len,
                    None,
                    None,
                    None,
                    None,
                )
            };
            if err == ERROR_NO_MORE_ITEMS || err != ERROR_SUCCESS {
                break;
            }
            names.push(String::from_utf16_lossy(&buf[..len as usize]));
        }
        names
    }
}

/// An in-memory registry for tests: key path (as first written) → values. Key names compare
/// ignoring ASCII case, like the registry.
#[cfg(test)]
#[derive(Debug, Default, Clone, PartialEq)]
pub struct FakeRegistry(
    pub std::collections::BTreeMap<String, std::collections::BTreeMap<String, RegValue>>,
);

#[cfg(test)]
impl FakeRegistry {
    fn find(&self, key: &str) -> Option<&String> {
        self.0.keys().find(|k| k.eq_ignore_ascii_case(key))
    }
    fn below(k: &str, key: &str) -> bool {
        k.len() > key.len() + 1
            && k.is_char_boundary(key.len())
            && k[..key.len()].eq_ignore_ascii_case(key)
            && k.as_bytes()[key.len()] == b'\\'
    }
}

#[cfg(test)]
impl Registry for FakeRegistry {
    fn set_values(&mut self, key: &str, values: &[(String, RegValue)]) -> Result<(), String> {
        split_key(key)?;
        let k = self.find(key).cloned().unwrap_or_else(|| key.to_string());
        let entry = self.0.entry(k).or_default();
        for (name, value) in values {
            let n = entry
                .keys()
                .find(|n| n.eq_ignore_ascii_case(name))
                .cloned()
                .unwrap_or_else(|| name.clone());
            entry.insert(n, value.clone());
        }
        Ok(())
    }
    fn delete_key(&mut self, key: &str) -> Result<(), String> {
        split_key(key)?;
        self.0
            .retain(|k, _| !k.eq_ignore_ascii_case(key) && !Self::below(k, key));
        Ok(())
    }
    fn delete_value(&mut self, key: &str, name: &str) -> Result<(), String> {
        if let Some(k) = self.find(key).cloned() {
            self.0
                .get_mut(&k)
                .unwrap()
                .retain(|n, _| !n.eq_ignore_ascii_case(name));
        }
        Ok(())
    }
    fn string(&self, key: &str, name: &str) -> Option<String> {
        let values = self.0.get(self.find(key)?)?;
        match values.iter().find(|(n, _)| n.eq_ignore_ascii_case(name))?.1 {
            RegValue::Sz(s) => Some(s.clone()),
            RegValue::Dword(_) => None,
        }
    }
    fn subkeys(&self, key: &str) -> Vec<String> {
        let mut names: Vec<String> = Vec::new();
        for k in self.0.keys().filter(|k| Self::below(k, key)) {
            let child = k[key.len() + 1..].split('\\').next().unwrap_or_default();
            if !names.iter().any(|n| n.eq_ignore_ascii_case(child)) {
                names.push(child.to_string());
            }
        }
        names
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_fake_registry_behaves_like_the_registry() {
        let mut r = FakeRegistry::default();
        let key = r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\MCPMonitor";
        r.set_values(
            key,
            &[("DisplayName".into(), RegValue::Sz("MCP Monitor".into()))],
        )
        .unwrap();
        r.set_values(
            &key.to_lowercase(),
            &[("displayname".into(), RegValue::Sz("new".into()))],
        )
        .unwrap();
        assert_eq!(r.0.len(), 1, "one key, case ignored: {r:?}");
        assert_eq!(r.string(key, "DisplayName").as_deref(), Some("new"));
        r.set_values(
            r"HKU\S-1-5-21-1\Software\Run",
            &[("MCPMonitor".into(), RegValue::Sz("x".into()))],
        )
        .unwrap();
        r.set_values(r"HKU\S-1-5-21-2\Software\Run", &[]).unwrap();
        assert_eq!(r.subkeys("HKU"), ["S-1-5-21-1", "S-1-5-21-2"]);
        assert_eq!(
            r.subkeys(r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            ["MCPMonitor"]
        );
        r.delete_value(r"HKU\S-1-5-21-1\Software\Run", "mcpmonitor")
            .unwrap();
        assert_eq!(r.string(r"HKU\S-1-5-21-1\Software\Run", "MCPMonitor"), None);
        r.delete_value(r"HKU\nope", "x").unwrap();
        r.delete_key(r"HKU\S-1-5-21-1").unwrap();
        assert_eq!(r.subkeys("HKU"), ["S-1-5-21-2"]);
        assert!(r.set_values(r"HKXX\a", &[]).is_err());
    }

    #[test]
    fn hive_prefixes_are_the_only_roots() {
        assert_eq!(
            split_key(r"HKLM\SOFTWARE\x").unwrap(),
            (HKEY_LOCAL_MACHINE, r"SOFTWARE\x")
        );
        assert_eq!(split_key(r"hku\S-1").unwrap(), (HKEY_USERS, "S-1"));
        assert_eq!(
            split_key(r"HKCU\Software").unwrap(),
            (HKEY_CURRENT_USER, "Software")
        );
        assert_eq!(split_key("HKLM").unwrap(), (HKEY_LOCAL_MACHINE, ""));
        for bad in [r"HKEY_LOCAL_MACHINE\x", r"C:\x", ""] {
            assert!(split_key(bad).is_err(), "{bad}");
        }
        assert!(
            WinRegistry.delete_key("HKLM").is_err(),
            "never a whole hive"
        );
    }

    #[test]
    fn the_real_registry_is_read_in_the_64_bit_view() {
        // Read only (Y23): a value every Windows has.
        let key = r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion";
        assert!(
            WinRegistry
                .string(key, "CurrentBuildNumber")
                .is_some_and(|b| b.parse::<u32>().is_ok())
        );
        assert_eq!(WinRegistry.string(key, "NoSuchValue"), None);
        assert!(
            WinRegistry
                .subkeys(r"HKLM\SOFTWARE\Microsoft")
                .iter()
                .any(|k| k.eq_ignore_ascii_case("Windows NT"))
        );
        assert!(
            WinRegistry
                .subkeys(r"HKLM\SOFTWARE\NoSuchKeyMcpMonitor")
                .is_empty()
        );
    }
}
