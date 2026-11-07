//! The server payload embedded in `mcp-monitor.exe`, and its verified extraction.
//!
//! `build.rs` packs the payload folder (`MCPMON_PAYLOAD_DIR`, else the small fixture payload) with
//! [`crate::payload_pack::pack_dir`] and writes the archive, its SHA-256, the manifest and the kind
//! into `OUT_DIR`; this module embeds them. Extraction trusts nothing in the archive: the whole
//! archive hash is checked first by the caller ([`verify_archive`]), then every entry must be a
//! regular file whose plain relative name is listed once in the manifest with the same size and
//! SHA-256, and every manifest file must appear (Y14).

use crate::payload_pack::{Manifest, name_problem, sha256_hex};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::fmt;
use std::fs;
use std::io::{self, Read, Write};
use std::path::{Component, Path};

/// The zstd-compressed tar of the payload.
pub static ARCHIVE: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/payload.tar.zst"));
/// Lower-case hex SHA-256 of [`ARCHIVE`].
pub const ARCHIVE_SHA256: &str = include_str!(concat!(env!("OUT_DIR"), "/payload.sha256"));
const MANIFEST_JSON: &str = include_str!(concat!(env!("OUT_DIR"), "/payload-manifest.json"));
/// `"fixture"` (built without `MCPMON_PAYLOAD_DIR`; never installed for real) or `"release"`.
pub const KIND: &str = include_str!(concat!(env!("OUT_DIR"), "/payload-kind.txt"));

/// Written first into every extraction folder, so a later clean-up can tell it is ours (Task 7).
pub const STAGING_MARKER: &str = ".mcp-monitor-staging";
const STAGING_MARKER_CONTENT: &str = r#"{"product":"mcp-monitor"}"#;

/// The embedded manifest. A manifest that does not parse is a build defect, so this panics.
pub fn manifest() -> Manifest {
    serde_json::from_str(MANIFEST_JSON).expect("embedded payload manifest is not valid JSON")
}

#[derive(Debug)]
pub enum PayloadError {
    /// The archive's SHA-256 is not the expected one (a cut or altered exe).
    ArchiveHash,
    /// The archive cannot be decompressed or read as tar.
    Corrupt(String),
    /// An entry that is not a regular file, has an unsafe or unlisted name, or comes twice.
    UnexpectedEntry(String),
    /// A file whose bytes do not match the manifest hash.
    FileHash(String),
    /// A file whose size does not match the manifest.
    Size(String),
    /// A manifest file that the archive does not hold (the first one).
    Missing(String),
    /// The extraction folder already exists.
    DestinationExists(String),
    /// Writing the extracted files failed.
    Io(String),
}

impl fmt::Display for PayloadError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::ArchiveHash => write!(
                f,
                "실행 파일 안의 payload가 손상되었습니다(해시 불일치). 실행 파일을 다시 받으세요."
            ),
            Self::Corrupt(e) => write!(f, "payload를 읽을 수 없습니다: {e}"),
            Self::UnexpectedEntry(p) => write!(f, "payload에 예상하지 않은 항목이 있습니다: {p}"),
            Self::FileHash(p) => write!(f, "{p}의 해시가 매니페스트와 다릅니다"),
            Self::Size(p) => write!(f, "{p}의 크기가 매니페스트와 다릅니다"),
            Self::Missing(p) => write!(f, "payload에 {p}이(가) 없습니다"),
            Self::DestinationExists(p) => write!(f, "풀 폴더가 이미 있습니다: {p}"),
            Self::Io(e) => write!(f, "payload를 풀지 못했습니다: {e}"),
        }
    }
}

impl std::error::Error for PayloadError {}

/// Checks the whole archive against its expected SHA-256 (compared as lower-case hex).
pub fn verify_archive(archive: &[u8], sha256: &str) -> Result<(), PayloadError> {
    if sha256_hex(archive) == sha256.to_ascii_lowercase() {
        Ok(())
    } else {
        Err(PayloadError::ArchiveHash)
    }
}

/// The entry's name when it is a plain relative `/`-separated path of allowed parts, else `None`.
///
/// The raw name must already be in its normal form: `a/./b`, `a//b`, `a\b`, a trailing `/`,
/// `..`, a root, a drive (`C:/x`, `C:x`) or a bad character all give `None`.
fn plain_name(raw: &[u8]) -> Option<&str> {
    let raw = std::str::from_utf8(raw).ok()?;
    let mut parts = Vec::new();
    for c in Path::new(raw).components() {
        match c {
            Component::Normal(p) => {
                let part = p.to_str()?;
                if name_problem(part).is_some() {
                    return None;
                }
                parts.push(part);
            }
            _ => return None,
        }
    }
    (!parts.is_empty() && parts.join("/") == raw).then_some(raw)
}

/// Extracts `archive` into the new folder `dest`, checking every entry against `m`.
///
/// Returns the number of file bytes written. On failure `dest` is left as it is; it holds
/// [`STAGING_MARKER`] (written first), so the caller can recognise and remove it (Task 7).
pub fn extract(archive: &[u8], m: &Manifest, dest: &Path) -> Result<u64, PayloadError> {
    let io_err = |what: &dyn fmt::Display, e: io::Error| PayloadError::Io(format!("{what}: {e}"));
    let corrupt = |e: io::Error| PayloadError::Corrupt(e.to_string());

    if let Some(parent) = dest.parent() {
        fs::create_dir_all(parent).map_err(|e| io_err(&parent.display(), e))?;
    }
    match fs::create_dir(dest) {
        Ok(()) => {}
        Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {
            return Err(PayloadError::DestinationExists(dest.display().to_string()));
        }
        Err(e) => return Err(io_err(&dest.display(), e)),
    }
    fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(dest.join(STAGING_MARKER))
        .and_then(|mut f| f.write_all(STAGING_MARKER_CONTENT.as_bytes()))
        .map_err(|e| io_err(&STAGING_MARKER, e))?;

    let wanted: HashMap<&str, _> = m.files.iter().map(|f| (f.path.as_str(), f)).collect();
    let mut seen = HashSet::new();
    let mut written = 0u64;
    let decoder = zstd::stream::read::Decoder::new(archive).map_err(corrupt)?;
    let mut tar = tar::Archive::new(decoder);
    let mut buf = vec![0u8; 64 * 1024];
    for entry in tar.entries().map_err(corrupt)? {
        let mut entry = entry.map_err(corrupt)?;
        let raw = entry.path_bytes().into_owned();
        let shown = || String::from_utf8_lossy(&raw).into_owned();
        if entry.header().entry_type() != tar::EntryType::Regular {
            return Err(PayloadError::UnexpectedEntry(shown()));
        }
        let Some(name) = plain_name(&raw) else {
            return Err(PayloadError::UnexpectedEntry(shown()));
        };
        let Some(expected) = wanted.get(name) else {
            return Err(PayloadError::UnexpectedEntry(name.to_string()));
        };
        if !seen.insert(name.to_string()) {
            return Err(PayloadError::UnexpectedEntry(name.to_string()));
        }
        if entry.size() != expected.size {
            return Err(PayloadError::Size(name.to_string()));
        }

        let mut target = dest.to_path_buf();
        target.extend(name.split('/'));
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent).map_err(|e| io_err(&name, e))?;
        }
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&target)
            .map_err(|e| io_err(&name, e))?;
        let mut hasher = Sha256::new();
        let mut size = 0u64;
        loop {
            let n = entry.read(&mut buf).map_err(corrupt)?;
            if n == 0 {
                break;
            }
            file.write_all(&buf[..n]).map_err(|e| io_err(&name, e))?;
            hasher.update(&buf[..n]);
            size += n as u64;
        }
        if size != expected.size {
            return Err(PayloadError::Size(name.to_string()));
        }
        if hex::encode(hasher.finalize()) != expected.sha256.to_ascii_lowercase() {
            return Err(PayloadError::FileHash(name.to_string()));
        }
        written += size;
    }
    // Read the zstd stream to its end, so a cut or damaged frame (checksum) is noticed too.
    io::copy(&mut tar.into_inner(), &mut io::sink()).map_err(corrupt)?;

    if let Some(missing) = m.files.iter().find(|f| !seen.contains(f.path.as_str())) {
        return Err(PayloadError::Missing(missing.path.clone()));
    }
    Ok(written)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::payload_pack::{
        Manifest, ManifestFile, PackedPayload, check_release_layout, pack_dir, sha256_hex,
    };
    use std::fs;
    use std::path::Path;

    fn sample(dir: &Path) {
        for d in ["bin/monitor", "web", "docs"] {
            fs::create_dir_all(dir.join(d)).unwrap();
        }
        fs::write(
            dir.join("bundle.json"),
            r#"{"layout":"pyinstaller","version":"1.1.0","python":"3.15.2","built_at":"x","commit":"y","agent":"desktop"}"#,
        )
        .unwrap();
        fs::write(
            dir.join("bin/monitor/mcp-monitor-server.exe"),
            b"MZ fake server",
        )
        .unwrap();
        for page in ["board", "admin", "notice"] {
            fs::write(
                dir.join(format!("web/{page}.html")),
                format!("<!doctype html>{page} 보드"),
            )
            .unwrap();
        }
        fs::write(dir.join("docs/OPERATIONS.md"), "# 운영").unwrap();
    }

    fn packed() -> (tempfile::TempDir, PackedPayload) {
        let src = tempfile::tempdir().unwrap();
        sample(src.path());
        let p = pack_dir(src.path(), 3).unwrap();
        (src, p)
    }

    #[test]
    fn pack_is_deterministic_and_extract_round_trips() {
        let (src, a) = packed();
        std::thread::sleep(std::time::Duration::from_millis(20));
        fs::write(
            src.path().join("web/board.html"),
            "<!doctype html>board 보드",
        )
        .unwrap(); // same bytes, newer mtime
        let b = pack_dir(src.path(), 3).unwrap();
        assert_eq!(a.archive, b.archive);
        assert_eq!(a.sha256, sha256_hex(&a.archive));
        verify_archive(&a.archive, &a.sha256).unwrap();
        let out = tempfile::tempdir().unwrap();
        let dest = out.path().join("MCP Monitor.staging");
        let written = extract(&a.archive, &a.manifest, &dest).unwrap();
        assert_eq!(
            written,
            a.manifest.files.iter().map(|f| f.size).sum::<u64>()
        );
        assert_eq!(
            fs::read(dest.join("bin/monitor/mcp-monitor-server.exe")).unwrap(),
            b"MZ fake server"
        );
        assert_eq!(
            fs::read_to_string(dest.join("web/board.html")).unwrap(),
            "<!doctype html>board 보드"
        );
        assert!(dest.join(STAGING_MARKER).is_file());
        let paths: Vec<&str> = a.manifest.files.iter().map(|f| f.path.as_str()).collect();
        assert_eq!(
            paths,
            [
                "bin/monitor/mcp-monitor-server.exe",
                "bundle.json",
                "docs/OPERATIONS.md",
                "web/admin.html",
                "web/board.html",
                "web/notice.html"
            ]
        );
        assert_eq!(a.manifest.bundle["agent"], "desktop");
    }

    #[test]
    fn a_wrong_archive_hash_is_refused() {
        let (_src, a) = packed();
        assert!(matches!(
            verify_archive(&a.archive, &"0".repeat(64)),
            Err(PayloadError::ArchiveHash)
        ));
        let mut cut = a.archive.clone();
        cut.truncate(cut.len() / 2);
        assert!(matches!(
            verify_archive(&cut, &a.sha256),
            Err(PayloadError::ArchiveHash)
        ));
        let out = tempfile::tempdir().unwrap();
        assert!(extract(&cut, &a.manifest, &out.path().join("s")).is_err());
    }

    #[test]
    fn a_file_whose_bytes_differ_from_the_manifest_is_refused() {
        let (_src, a) = packed();
        let mut m = a.manifest.clone();
        m.files[0].sha256 = "0".repeat(64);
        let out = tempfile::tempdir().unwrap();
        match extract(&a.archive, &m, &out.path().join("s")) {
            Err(PayloadError::FileHash(p)) => assert_eq!(p, "bin/monitor/mcp-monitor-server.exe"),
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn an_entry_missing_from_the_manifest_is_refused() {
        let (_src, a) = packed();
        let mut m = a.manifest.clone();
        m.files.retain(|f| f.path != "web/notice.html");
        let out = tempfile::tempdir().unwrap();
        assert!(
            matches!(extract(&a.archive, &m, &out.path().join("s")), Err(PayloadError::UnexpectedEntry(p)) if p == "web/notice.html")
        );
    }

    #[test]
    fn a_manifest_file_missing_from_the_archive_is_refused() {
        let (_src, a) = packed();
        let mut m = a.manifest.clone();
        m.files.push(ManifestFile {
            path: "web/extra.html".into(),
            size: 1,
            sha256: "0".repeat(64),
        });
        let out = tempfile::tempdir().unwrap();
        assert!(
            matches!(extract(&a.archive, &m, &out.path().join("s")), Err(PayloadError::Missing(p)) if p == "web/extra.html")
        );
    }

    /// A one-entry tar.zst whose header name is written byte for byte (`Header::set_path` refuses `..`).
    fn raw_archive(name: &str, kind: tar::EntryType) -> Vec<u8> {
        let mut header = tar::Header::new_gnu();
        let bytes = name.as_bytes();
        header.as_gnu_mut().unwrap().name[..bytes.len()].copy_from_slice(bytes);
        header.set_entry_type(kind);
        header.set_size(if kind == tar::EntryType::Regular {
            1
        } else {
            0
        });
        header.set_mode(0o644);
        if kind != tar::EntryType::Regular {
            header.set_link_name("target").unwrap();
        }
        header.set_cksum();
        let mut b = tar::Builder::new(Vec::new());
        let data: &[u8] = if kind == tar::EntryType::Regular {
            b"x"
        } else {
            b""
        };
        b.append(&header, data).unwrap();
        zstd::encode_all(&b.into_inner().unwrap()[..], 3).unwrap()
    }

    #[test]
    fn traversal_absolute_and_link_entries_are_refused() {
        let out = tempfile::tempdir().unwrap();
        let cases = [
            ("../evil.exe", tar::EntryType::Regular),
            ("a/../../evil.exe", tar::EntryType::Regular),
            ("/evil.exe", tar::EntryType::Regular),
            ("C:/evil.exe", tar::EntryType::Regular),
            ("C:evil.exe", tar::EntryType::Regular),
            ("web/link", tar::EntryType::Symlink),
            ("web/hard", tar::EntryType::Link),
            ("web/dir/", tar::EntryType::Directory),
        ];
        for (i, (name, kind)) in cases.into_iter().enumerate() {
            let m = Manifest {
                files: vec![ManifestFile {
                    path: name.into(),
                    size: 1,
                    sha256: sha256_hex(b"x"),
                }],
                bundle: serde_json::json!({}),
            };
            let dest = out.path().join(format!("s{i}"));
            assert!(
                matches!(
                    extract(&raw_archive(name, kind), &m, &dest),
                    Err(PayloadError::UnexpectedEntry(_))
                ),
                "{name}"
            );
        }
        assert!(!out.path().join("evil.exe").exists());
        assert!(!Path::new("C:/evil.exe").exists());
    }

    /// A tar.zst of regular files whose names are written byte for byte.
    fn raw_files(files: &[(&str, &[u8])]) -> Vec<u8> {
        let mut b = tar::Builder::new(Vec::new());
        for (name, data) in files {
            let mut header = tar::Header::new_gnu();
            header.as_gnu_mut().unwrap().name[..name.len()].copy_from_slice(name.as_bytes());
            header.set_entry_type(tar::EntryType::Regular);
            header.set_size(data.len() as u64);
            header.set_mode(0o644);
            header.set_cksum();
            b.append(&header, *data).unwrap();
        }
        zstd::encode_all(&b.into_inner().unwrap()[..], 3).unwrap()
    }

    fn listing(names: &[&str], data: &[u8]) -> Manifest {
        Manifest {
            files: names
                .iter()
                .map(|n| ManifestFile {
                    path: (*n).into(),
                    size: data.len() as u64,
                    sha256: sha256_hex(data),
                })
                .collect(),
            bundle: serde_json::json!({}),
        }
    }

    #[test]
    fn a_cut_archive_is_corrupt_and_the_marker_is_written_first() {
        let (_src, a) = packed();
        let cut = &a.archive[..a.archive.len() - 8];
        let out = tempfile::tempdir().unwrap();
        let dest = out.path().join("s");
        assert!(matches!(
            extract(cut, &a.manifest, &dest),
            Err(PayloadError::Corrupt(_))
        ));
        assert_eq!(
            fs::read_to_string(dest.join(STAGING_MARKER)).unwrap(),
            r#"{"product":"mcp-monitor"}"#
        );
    }

    #[test]
    fn duplicate_and_non_plain_names_are_refused() {
        let out = tempfile::tempdir().unwrap();
        let twice = raw_files(&[("a.txt", b"x"), ("a.txt", b"x")]);
        assert!(
            matches!(extract(&twice, &listing(&["a.txt"], b"x"), &out.path().join("d")), Err(PayloadError::UnexpectedEntry(p)) if p == "a.txt")
        );
        let names = [
            "a/./b.txt",
            "a//b.txt",
            r"a\b.txt",
            "./b.txt",
            "web/a.html:stream",
            "web/a.html.",
            "web/a.html ",
            "web/a\u{1}.html",
        ];
        for (i, name) in names.into_iter().enumerate() {
            let dest = out.path().join(format!("n{i}"));
            assert!(
                matches!(
                    extract(&raw_files(&[(name, b"x")]), &listing(&[name], b"x"), &dest),
                    Err(PayloadError::UnexpectedEntry(_))
                ),
                "{name}"
            );
            assert_eq!(fs::read_dir(&dest).unwrap().count(), 1, "{name}");
        }
    }

    #[test]
    fn a_size_that_differs_from_the_manifest_is_refused_before_writing() {
        let out = tempfile::tempdir().unwrap();
        let dest = out.path().join("s");
        let mut m = listing(&["a.txt"], b"xy");
        m.files[0].size = 1;
        assert!(
            matches!(extract(&raw_files(&[("a.txt", b"xy")]), &m, &dest), Err(PayloadError::Size(p)) if p == "a.txt")
        );
        assert!(!dest.join("a.txt").exists());
    }

    #[test]
    fn pack_needs_a_bundle_json_object() {
        let src = tempfile::tempdir().unwrap();
        sample(src.path());
        fs::remove_file(src.path().join("bundle.json")).unwrap();
        assert!(pack_dir(src.path(), 3).unwrap_err().contains("bundle.json"));
        fs::write(src.path().join("bundle.json"), "[1]").unwrap();
        assert!(pack_dir(src.path(), 3).unwrap_err().contains("bundle.json"));
        // Only the root bundle.json counts.
        fs::remove_file(src.path().join("bundle.json")).unwrap();
        fs::write(src.path().join("web/bundle.json"), "{}").unwrap();
        assert!(pack_dir(src.path(), 3).unwrap_err().contains("bundle.json"));
    }

    #[test]
    fn errors_read_in_korean() {
        assert_eq!(
            PayloadError::ArchiveHash.to_string(),
            "실행 파일 안의 payload가 손상되었습니다(해시 불일치). 실행 파일을 다시 받으세요."
        );
        assert_eq!(
            PayloadError::FileHash("web/board.html".into()).to_string(),
            "web/board.html의 해시가 매니페스트와 다릅니다"
        );
    }

    #[test]
    fn extract_refuses_an_existing_destination() {
        let (_src, a) = packed();
        let out = tempfile::tempdir().unwrap();
        let dest = out.path().join("s");
        fs::create_dir(&dest).unwrap();
        assert!(matches!(
            extract(&a.archive, &a.manifest, &dest),
            Err(PayloadError::DestinationExists(_))
        ));
        assert_eq!(fs::read_dir(&dest).unwrap().count(), 0);
    }

    #[test]
    fn release_layout_needs_the_server_web_and_matching_version() {
        let (src, a) = packed();
        check_release_layout(&a.manifest, "1.1.0").unwrap();
        assert!(
            check_release_layout(&a.manifest, "1.2.0")
                .unwrap_err()
                .contains("1.2.0")
        );
        fs::remove_file(src.path().join("web/notice.html")).unwrap();
        assert!(
            check_release_layout(&pack_dir(src.path(), 3).unwrap().manifest, "1.1.0")
                .unwrap_err()
                .contains("web/notice.html")
        );
        sample(src.path());
        fs::write(src.path().join("mcp-monitor.exe"), b"x").unwrap();
        assert!(
            check_release_layout(&pack_dir(src.path(), 3).unwrap().manifest, "1.1.0")
                .unwrap_err()
                .contains("mcp-monitor.exe")
        );
        fs::remove_file(src.path().join("mcp-monitor.exe")).unwrap();
        fs::write(
            src.path().join("bundle.json"),
            r#"{"layout":"pyinstaller","version":"1.1.0","agent":"python"}"#,
        )
        .unwrap();
        assert!(
            check_release_layout(&pack_dir(src.path(), 3).unwrap().manifest, "1.1.0")
                .unwrap_err()
                .contains("agent")
        );
    }

    #[test]
    fn pack_refuses_links() {
        let src = tempfile::tempdir().unwrap();
        sample(src.path());
        let target = tempfile::tempdir().unwrap();
        let ok = std::process::Command::new(crate::winutil::system_tool("cmd.exe"))
            .args(["/d", "/c", "mklink", "/J"])
            .arg(src.path().join("web").join("j"))
            .arg(target.path())
            .output()
            .unwrap()
            .status
            .success();
        assert!(ok);
        assert!(pack_dir(src.path(), 3).unwrap_err().contains("web/j"));
    }

    #[test]
    fn embedded_payload_verifies_and_matches_its_manifest() {
        verify_archive(ARCHIVE, ARCHIVE_SHA256).unwrap();
        let m = manifest();
        assert_eq!(
            (m.bundle["layout"].as_str(), m.bundle["agent"].as_str()),
            (Some("pyinstaller"), Some("desktop"))
        );
        assert!(["fixture", "release"].contains(&KIND));
        let out = tempfile::tempdir().unwrap();
        extract(ARCHIVE, &m, &out.path().join("s")).unwrap();
        assert!(
            out.path()
                .join("s/bin/monitor/mcp-monitor-server.exe")
                .is_file()
        );
    }
}
