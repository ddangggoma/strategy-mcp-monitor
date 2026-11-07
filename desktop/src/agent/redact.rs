//! Keeps the notice token out of window titles (Y9, Y22): the same expression as the server's
//! `app.activity.redact.redact_notice_tokens`, applied in the agent too as an extra defence.

use regex::Regex;
use std::sync::OnceLock;

pub const REDACTED: &str = "<redacted>";

/// The server's `(/notice#(?:[^\s"'#&]*&)*t=)[^\s"'&#]+`. Python's `\s` (str) also matches
/// U+001C–U+001F, which Rust's Unicode `\s` does not, so they are listed explicitly.
const NOTICE_TOKEN: &str = r#"(/notice#(?:[^\s\x1C-\x1F"'#&]*&)*t=)[^\s\x1C-\x1F"'&#]+"#;

fn notice_token() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(NOTICE_TOKEN).expect("the notice token expression compiles"))
}

/// `text` with every notice-page token (`/notice#…t=<token>`) replaced by `<redacted>`.
pub fn redact_notice_tokens(text: &str) -> String {
    notice_token()
        .replace_all(text, |c: &regex::Captures<'_>| {
            format!("{}{REDACTED}", &c[1])
        })
        .into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redacts_like_the_server() {
        let cases = [
            (
                "msedge --app=http://127.0.0.1:8700/notice#d=1&t=abc",
                "msedge --app=http://127.0.0.1:8700/notice#d=1&t=<redacted>",
            ),
            (
                "x http://localhost:8700/notice#t=abc&d=1 y",
                "x http://localhost:8700/notice#t=<redacted>&d=1 y",
            ),
            (
                "x 'http://[::1]:8700/notice#d=1&t=a%2Fb' y",
                "x 'http://[::1]:8700/notice#d=1&t=<redacted>' y",
            ),
            (
                "x https://example.com/watch?v=1&t=30 y",
                "x https://example.com/watch?v=1&t=30 y",
            ),
            ("notepad.exe a.txt", "notepad.exe a.txt"),
        ];
        for (raw, clean) in cases {
            assert_eq!(redact_notice_tokens(raw), clean, "{raw}");
        }
    }

    #[test]
    fn every_token_goes_and_python_whitespace_ends_one() {
        assert_eq!(
            redact_notice_tokens("/notice#t=a /notice#d=2&t=b\u{1f}c"),
            "/notice#t=<redacted> /notice#d=2&t=<redacted>\u{1f}c"
        );
        assert_eq!(
            redact_notice_tokens("/notice#t=a\u{3000}b"),
            "/notice#t=<redacted>\u{3000}b"
        );
    }
}
