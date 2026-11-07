//! Deterministic payload packing, shared by `build.rs` (via `#[path]`) and the crate.
//!
//! The archive is a GNU tar of regular files only — sorted by relative path bytes, mode 0o644,
//! mtime 0, uid/gid 0, no user or group names, no directory entries — compressed with zstd, so the
//! same folder always gives the same bytes whatever its file times are. Every file is also listed
//! in a manifest with its size and SHA-256, which extraction checks one file at a time (Y14).
//!
//! This file is compiled twice (into the build script and into the crate), so it must not refer
//! to `crate::` items.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs;
use std::os::windows::fs::MetadataExt;
use std::path::{Component, Path};

/// `FILE_ATTRIBUTE_REPARSE_POINT`: junctions, symbolic links and other reparse points.
const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;

/// Files at the payload root that a release payload must have.
const RELEASE_FILES: [&str; 5] = [
    "bundle.json",
    "bin/monitor/mcp-monitor-server.exe",
    "web/board.html",
    "web/admin.html",
    "web/notice.html",
];

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
pub struct ManifestFile {
    /// Relative path with `/` separators.
    pub path: String,
    pub size: u64,
    /// Lower-case hex SHA-256 of the file bytes.
    pub sha256: String,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
pub struct Manifest {
    /// Sorted by `path` bytes.
    pub files: Vec<ManifestFile>,
    /// The payload's `bundle.json`.
    pub bundle: serde_json::Value,
}

pub struct PackedPayload {
    pub archive: Vec<u8>,
    pub manifest: Manifest,
    /// Lower-case hex SHA-256 of `archive`.
    pub sha256: String,
}

/// Short form: the archive bytes are not printed.
impl std::fmt::Debug for PackedPayload {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("PackedPayload")
            .field("archive_len", &self.archive.len())
            .field("files", &self.manifest.files.len())
            .field("sha256", &self.sha256)
            .finish()
    }
}

/// Lower-case hex SHA-256 (64 characters).
pub fn sha256_hex(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

/// Why one part of a payload name is not allowed, or `None` when it is fine.
///
/// A part must not be empty, `.` or `..`, must not hold `\ / : * ? " < > |` or a control
/// character, and must not end in `.` or a space (Windows would silently drop those).
pub fn name_problem(part: &str) -> Option<&'static str> {
    if part.is_empty() {
        Some("빈 이름")
    } else if part == "." || part == ".." {
        Some("'.'이나 '..'은 쓸 수 없습니다")
    } else if part
        .chars()
        .any(|c| c.is_control() || r#"\/:*?"<>|"#.contains(c))
    {
        Some("이름에 쓸 수 없는 문자가 있습니다")
    } else if part.ends_with('.') || part.ends_with(' ') {
        Some("이름이 '.'이나 공백으로 끝납니다")
    } else {
        None
    }
}

fn is_link(meta: &fs::Metadata) -> bool {
    meta.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 || meta.file_type().is_symlink()
}

fn link_error(name: &str) -> String {
    format!("{name}: 링크는 payload에 넣을 수 없습니다")
}

/// The `/`-joined name of `path` below `root`, with every part checked by [`name_problem`].
fn relative_name(root: &Path, path: &Path) -> Result<String, String> {
    let rel = path
        .strip_prefix(root)
        .map_err(|_| format!("{}: payload 폴더 밖의 항목입니다", path.display()))?;
    let mut parts = Vec::new();
    for c in rel.components() {
        let part = match c {
            Component::Normal(p) => p
                .to_str()
                .ok_or_else(|| format!("{}: 이름이 유니코드가 아닙니다", rel.display()))?,
            _ => return Err(format!("{}: 잘못된 경로입니다", rel.display())),
        };
        if let Some(why) = name_problem(part) {
            return Err(format!("{}: {why}", rel.display()));
        }
        parts.push(part);
    }
    Ok(parts.join("/"))
}

/// Packs every regular file below `dir` into a deterministic tar.zst (see the module docs).
///
/// Refuses links (junctions, symbolic links, any reparse point) anywhere, including `dir` itself,
/// bad names, and a payload whose `bundle.json` is missing or not a JSON object.
pub fn pack_dir(dir: &Path, level: i32) -> Result<PackedPayload, String> {
    let root_meta = fs::symlink_metadata(dir).map_err(|e| format!("{}: {e}", dir.display()))?;
    if is_link(&root_meta) {
        return Err(link_error(&dir.display().to_string()));
    }
    if !root_meta.is_dir() {
        return Err(format!("{}: 폴더가 아닙니다", dir.display()));
    }

    let mut found = Vec::new();
    for entry in walkdir::WalkDir::new(dir).follow_links(false).min_depth(1) {
        let entry = entry.map_err(|e| e.to_string())?;
        let name = relative_name(dir, entry.path())?;
        let meta = entry.metadata().map_err(|e| format!("{name}: {e}"))?;
        if entry.path_is_symlink() || is_link(&meta) {
            return Err(link_error(&name));
        }
        if meta.is_dir() {
            continue;
        }
        if !meta.is_file() {
            return Err(format!("{name}: 정규 파일이 아닙니다"));
        }
        found.push((name, entry.into_path()));
    }
    found.sort_by(|a, b| a.0.as_bytes().cmp(b.0.as_bytes()));

    let io = |name: &str, e: std::io::Error| format!("{name}: {e}");
    let mut encoder =
        zstd::stream::write::Encoder::new(Vec::new(), level).map_err(|e| io("zstd", e))?;
    encoder.include_checksum(true).map_err(|e| io("zstd", e))?;
    let mut builder = tar::Builder::new(encoder);
    let mut files = Vec::with_capacity(found.len());
    let mut bundle = None;
    for (name, path) in found {
        let bytes = fs::read(&path).map_err(|e| io(&name, e))?;
        if name == "bundle.json" {
            let value: serde_json::Value = serde_json::from_slice(&bytes)
                .map_err(|e| format!("bundle.json: JSON이 아닙니다: {e}"))?;
            if !value.is_object() {
                return Err("bundle.json: JSON 객체가 아닙니다".into());
            }
            bundle = Some(value);
        }
        let mut header = tar::Header::new_gnu();
        header.set_entry_type(tar::EntryType::Regular);
        header.set_size(bytes.len() as u64);
        header.set_mode(0o644);
        header.set_uid(0);
        header.set_gid(0);
        header.set_mtime(0);
        builder
            .append_data(&mut header, &name, bytes.as_slice())
            .map_err(|e| io(&name, e))?;
        files.push(ManifestFile {
            sha256: sha256_hex(&bytes),
            size: bytes.len() as u64,
            path: name,
        });
    }
    let bundle = bundle.ok_or("bundle.json이 없습니다")?;
    let archive = builder
        .into_inner()
        .and_then(|encoder| encoder.finish())
        .map_err(|e| io("tar", e))?;
    let sha256 = sha256_hex(&archive);
    Ok(PackedPayload {
        archive,
        manifest: Manifest { files, bundle },
        sha256,
    })
}

/// Checks that a payload is a complete release payload for this exe's version (Y14).
///
/// Every problem is listed in the error, each naming the file or `bundle.json` key at fault.
pub fn check_release_layout(m: &Manifest, cargo_version: &str) -> Result<(), String> {
    let mut problems = Vec::new();
    for required in RELEASE_FILES {
        if !m.files.iter().any(|f| f.path == required) {
            problems.push(format!("{required}이(가) 없습니다"));
        }
    }
    for (key, want) in [
        ("layout", "pyinstaller"),
        ("agent", "desktop"),
        ("version", cargo_version),
    ] {
        let got = m.bundle.get(key);
        if got.and_then(|v| v.as_str()) != Some(want) {
            let got = got.map_or_else(|| "없음".to_string(), |v| v.to_string());
            problems.push(format!(
                "bundle.json의 {key}가 {got}입니다({want}이어야 합니다)"
            ));
        }
    }
    if m.files
        .iter()
        .any(|f| f.path.eq_ignore_ascii_case("mcp-monitor.exe"))
    {
        problems.push("루트에 mcp-monitor.exe가 있습니다(설치기가 자신을 넣습니다)".into());
    }
    if problems.is_empty() {
        Ok(())
    } else {
        Err(problems.join("; "))
    }
}
