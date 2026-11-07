//! Product version and the `--version` line.

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Version(pub u32, pub u32, pub u32);

impl Version {
    /// Exactly `digits.digits.digits`: no spaces, suffixes, signs or empty parts; each part fits a `u32`.
    pub fn parse(s: &str) -> Option<Version> {
        let mut parts = s.split('.');
        let mut next = || -> Option<u32> {
            let part = parts.next()?;
            if part.is_empty() || !part.bytes().all(|b| b.is_ascii_digit()) {
                return None;
            }
            part.parse().ok()
        };
        let version = Version(next()?, next()?, next()?);
        if parts.next().is_some() {
            return None;
        }
        Some(version)
    }
}

pub const PRODUCT: &str = env!("CARGO_PKG_VERSION");

/// `mcp-monitor <product> (payload <first 12 of sha>, <kind>[, dev])`.
pub fn version_line(product: &str, payload_sha: &str, kind: &str, dev: bool) -> String {
    let short: String = payload_sha.chars().take(12).collect();
    let dev = if dev { ", dev" } else { "" };
    format!("mcp-monitor {product} (payload {short}, {kind}{dev})")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_and_compares_versions() {
        assert_eq!(Version::parse("1.1.0"), Some(Version(1, 1, 0)));
        assert!(Version::parse("1.10.0").unwrap() > Version::parse("1.9.9").unwrap());
        assert!(Version::parse("2.0.0").unwrap() > Version::parse("1.99.99").unwrap());
        for bad in [
            "1.1",
            "1.1.0-rc1",
            " 1.1.0",
            "1.1.0 ",
            "+1.1.0",
            "1..0",
            "a.b.c",
            "1.1.0.0",
            "",
        ] {
            assert_eq!(Version::parse(bad), None, "{bad:?}");
        }
    }

    #[test]
    fn version_line_names_the_payload() {
        assert_eq!(
            version_line("1.1.0", "0123456789abcdef", "fixture", false),
            "mcp-monitor 1.1.0 (payload 0123456789ab, fixture)"
        );
        assert_eq!(
            version_line("1.1.0", "0123456789abcdef", "release", true),
            "mcp-monitor 1.1.0 (payload 0123456789ab, release, dev)"
        );
        assert_eq!(PRODUCT, "1.1.0");
    }
}
