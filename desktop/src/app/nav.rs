//! Where the app window may go (Y11): the local channel `http://127.0.0.1:<local port>` and the
//! "connecting" page (`http://tauri.localhost/…`) stay in the window; any other `http`/`https`
//! address opens in the default browser; everything else (user info in the address, `file:`,
//! `javascript:`, `data:`, `ms-*:`, `about:`, unparsable text) is refused. New-window requests
//! follow the same table (an allowed one opens in the same window: no second window is made).

use tauri::Url;

#[derive(Debug, PartialEq)]
pub enum NavDecision {
    Allow,
    OpenExternal,
    Block,
}

/// The decision for `url` in the app window of a server whose local channel is `local_port`.
/// Hosts are compared as the URL parser writes them (an IPv4 address in dotted decimal, a domain
/// in lower case), so `127.1` is `127.0.0.1` and `127.0.0.1.evil.example` is a domain.
pub fn classify_navigation(url: &str, local_port: u16) -> NavDecision {
    let Ok(u) = Url::parse(url) else {
        return NavDecision::Block;
    };
    let http = u.scheme() == "http";
    if !(http || u.scheme() == "https") || !u.username().is_empty() || u.password().is_some() {
        return NavDecision::Block;
    }
    let port = u.port_or_known_default();
    match u.host_str() {
        Some("127.0.0.1") if http && port == Some(local_port) => NavDecision::Allow,
        Some("tauri.localhost") if http && port == Some(80) => NavDecision::Allow,
        Some(_) => NavDecision::OpenExternal,
        None => NavDecision::Block,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use NavDecision::*;

    #[test]
    fn classify_navigation_table() {
        let cases = [
            ("http://127.0.0.1:8700/admin", Allow),
            ("http://127.0.0.1:8700/admin/logs?from=1#x", Allow),
            ("http://127.0.0.1:8700/notice#d=1&t=x", Allow),
            ("http://tauri.localhost/index.html#stopped", Allow),
            ("http://127.0.0.1:8701/", OpenExternal),
            ("http://localhost:8700/admin", OpenExternal),
            ("http://127.0.0.1.evil.example:8700/", OpenExternal),
            ("https://example.com/docs", OpenExternal),
            ("http://[::1]:8700/admin", OpenExternal),
            ("http://user@127.0.0.1:8700/admin", Block),
            ("file:///C:/Windows/win.ini", Block),
            ("javascript:alert(1)", Block),
            ("data:text/html,x", Block),
            ("ms-settings:privacy", Block),
            ("about:blank", Block),
            ("not a url", Block),
        ];
        for (url, want) in cases {
            assert_eq!(classify_navigation(url, 8700), want, "{url}");
        }
        assert_eq!(
            classify_navigation("http://127.0.0.1:9700/admin", 9700),
            Allow
        );
        assert_eq!(
            classify_navigation("http://127.0.0.1:8700/admin", 9700),
            OpenExternal
        );
    }

    #[test]
    fn near_misses_of_the_two_allowed_origins_leave_the_window() {
        let cases = [
            // the local channel over https, or on the default port, is not the server
            ("https://127.0.0.1:8700/admin", OpenExternal),
            ("http://127.0.0.1/admin", OpenExternal),
            ("http://127.0.0.2:8700/admin", OpenExternal),
            ("http://0.0.0.0:8700/admin", OpenExternal),
            ("https://tauri.localhost/index.html", OpenExternal),
            ("http://tauri.localhost:8080/index.html", OpenExternal),
            ("http://evil.tauri.localhost/", OpenExternal),
            // user info anywhere in an http(s) address is refused, not opened
            ("http://:secret@127.0.0.1:8700/admin", Block),
            ("https://user:pw@example.com/", Block),
            ("http://u@tauri.localhost/index.html", Block),
            ("ftp://example.com/", Block),
            ("view-source:http://127.0.0.1:8700/admin", Block),
            ("edge://settings", Block),
            ("", Block),
        ];
        for (url, want) in cases {
            assert_eq!(classify_navigation(url, 8700), want, "{url}");
        }
        // the parser's spelling of 127.0.0.1 is the address itself
        assert_eq!(classify_navigation("http://127.1:8700/admin", 8700), Allow);
        assert_eq!(classify_navigation("HTTP://127.0.0.1:8700/", 8700), Allow);
        assert_eq!(classify_navigation("http://127.0.0.1:80/", 80), Allow);
    }
}
