//! The agent's launch secrets and settings (Python `mcp_agent.config`).
//!
//! The service starts `mcp-monitor.exe agent --server … --dialog …` with the per-launch token in
//! `MCPMON_AGENT_TOKEN` and the key the server proves itself with in `MCPMON_AGENT_SERVER_KEY`
//! (Plan 4 I1). Both are taken out of the environment first, whatever fails next, so no child
//! process (WebView2) ever inherits them.

use crate::cli::{AgentArgs, ArgError, Dialog};
use std::collections::HashMap;
use std::path::PathBuf;

pub const TOKEN_ENV: &str = "MCPMON_AGENT_TOKEN";
pub const SERVER_KEY_ENV: &str = "MCPMON_AGENT_SERVER_KEY";
pub const SERVER_KEY_BYTES: usize = 32;
const WEBVIEW2_PREFIX: &str = "WEBVIEW2_";

/// The environment as the agent needs it; [`ProcessEnv`] is the real one, a `HashMap` the test one.
pub trait EnvAccess {
    /// The value of `name` (if any), removed from the environment.
    fn take(&mut self, name: &str) -> Option<String>;
    fn names(&self) -> Vec<String>;
    fn remove(&mut self, name: &str);
}

/// This process's environment.
pub struct ProcessEnv;

impl EnvAccess for ProcessEnv {
    fn take(&mut self, name: &str) -> Option<String> {
        let value = std::env::var_os(name)?;
        self.remove(name);
        // A value that is not Unicode is no usable token or key; it is removed all the same.
        value.into_string().ok()
    }
    fn names(&self) -> Vec<String> {
        std::env::vars_os()
            .map(|(name, _)| name.to_string_lossy().into_owned())
            .collect()
    }
    fn remove(&mut self, name: &str) {
        // SAFETY: agent mode calls this first thing, before it starts any thread (the heartbeat
        // thread and the window come later). On Windows the call is `SetEnvironmentVariableW`
        // made under std's own environment lock, so the unit tests that run `run_with` on the
        // test harness's threads only meet other `std::env` users, which take the same lock.
        unsafe { std::env::remove_var(name) }
    }
}

impl EnvAccess for HashMap<String, String> {
    fn take(&mut self, name: &str) -> Option<String> {
        self.remove(name)
    }
    fn names(&self) -> Vec<String> {
        self.keys().cloned().collect()
    }
    fn remove(&mut self, name: &str) {
        HashMap::remove(self, name);
    }
}

/// `(token, server key)`, both removed from `env` at once (also when one of them is missing).
pub fn take_secrets(env: &mut dyn EnvAccess) -> (Option<String>, Option<String>) {
    let token = env.take(TOKEN_ENV);
    let key = env.take(SERVER_KEY_ENV);
    (token, key)
}

/// Removes every variable whose name starts with `WEBVIEW2_` (any case) and returns their names:
/// a user's environment must not turn on remote debugging or another runtime in our WebView2
/// windows (Y24; not called in `dev` builds).
pub fn strip_webview2_env(env: &mut dyn EnvAccess) -> Vec<String> {
    let gone: Vec<String> = env
        .names()
        .into_iter()
        .filter(|name| {
            name.get(..WEBVIEW2_PREFIX.len())
                .is_some_and(|p| p.eq_ignore_ascii_case(WEBVIEW2_PREFIX))
        })
        .collect();
    for name in &gone {
        env.remove(name);
    }
    gone
}

pub struct AgentConfig {
    /// `http://…` without a trailing `/`.
    pub server: String,
    pub token: String,
    pub server_key: [u8; 32],
    pub dialog: Dialog,
    pub url_file: Option<PathBuf>,
    pub unreachable_exit_sec: f64,
}

/// Never shows the token or the key.
impl std::fmt::Debug for AgentConfig {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("AgentConfig")
            .field("server", &self.server)
            .field("token", &"<redacted>")
            .field("server_key", &"<redacted>")
            .field("dialog", &self.dialog)
            .field("url_file", &self.url_file)
            .field("unreachable_exit_sec", &self.unreachable_exit_sec)
            .finish()
    }
}

/// The settings from the parsed arguments and the two secrets (from [`take_secrets`]).
pub fn config_from(
    args: &AgentArgs,
    token: Option<String>,
    key: Option<String>,
) -> Result<AgentConfig, ArgError> {
    let Some(token) = token.filter(|t| !t.is_empty()) else {
        return Err(ArgError(format!("{TOKEN_ENV}이 없습니다")));
    };
    let Some(server_key) = key.as_deref().and_then(parse_key) else {
        return Err(ArgError(format!(
            "{SERVER_KEY_ENV}는 {SERVER_KEY_BYTES}바이트 hex여야 합니다"
        )));
    };
    if !args.server.starts_with("http://") {
        return Err(ArgError(format!(
            "--server는 http://로 시작하는 주소여야 합니다: {}",
            args.server
        )));
    }
    Ok(AgentConfig {
        server: args.server.trim_end_matches('/').to_string(),
        token,
        server_key,
        dialog: args.dialog,
        url_file: args.url_file.clone(),
        unreachable_exit_sec: args.unreachable_exit_sec,
    })
}

/// Exactly 64 hex digits (either case) → 32 bytes.
fn parse_key(key: &str) -> Option<[u8; 32]> {
    if key.len() != 2 * SERVER_KEY_BYTES {
        return None;
    }
    hex::decode(key).ok()?.try_into().ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cli::{AgentArgs, Dialog};
    use std::collections::HashMap;

    fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }
    fn args() -> AgentArgs {
        AgentArgs {
            server: "http://127.0.0.1:8700/".into(),
            dialog: Dialog::Webview,
            url_file: None,
            unreachable_exit_sec: 120.0,
        }
    }

    #[test]
    fn secrets_are_taken_out_of_the_environment() {
        let mut e = env(&[
            (TOKEN_ENV, "tok"),
            (SERVER_KEY_ENV, &"11".repeat(32)),
            ("PATH", "x"),
        ]);
        let (t, k) = take_secrets(&mut e);
        assert_eq!(
            (t.as_deref(), k.as_deref()),
            (Some("tok"), Some("11".repeat(32).as_str()))
        );
        assert!(
            !e.contains_key(TOKEN_ENV) && !e.contains_key(SERVER_KEY_ENV) && e.contains_key("PATH")
        );
        let cfg = config_from(&args(), t, k).unwrap();
        assert_eq!(
            (cfg.server.as_str(), cfg.server_key),
            ("http://127.0.0.1:8700", [0x11; 32])
        );
    }

    #[test]
    fn a_missing_token_or_a_bad_key_is_an_argument_error_and_still_removed() {
        for key in [
            None,
            Some(""),
            Some("zz".repeat(32).leak() as &str),
            Some("11".repeat(16).leak() as &str),
        ] {
            let mut e = env(&[(TOKEN_ENV, "t")]);
            if let Some(k) = key {
                e.insert(SERVER_KEY_ENV.into(), k.into());
            }
            let (t, k) = take_secrets(&mut e);
            assert!(
                config_from(&args(), t, k)
                    .unwrap_err()
                    .0
                    .contains(SERVER_KEY_ENV)
            );
            assert!(e.is_empty());
        }
        assert!(
            config_from(&args(), None, Some("11".repeat(32)))
                .unwrap_err()
                .0
                .contains(TOKEN_ENV)
        );
        assert!(config_from(&args(), Some(String::new()), Some("11".repeat(32))).is_err());
        let ftp = AgentArgs {
            server: "ftp://127.0.0.1:8700".into(),
            ..args()
        };
        assert!(config_from(&ftp, Some("t".into()), Some("11".repeat(32))).is_err());
    }

    #[test]
    fn webview2_variables_are_removed() {
        let mut e = env(&[
            (
                "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
                "--remote-debugging-port=9222",
            ),
            ("webview2_browser_executable_folder", r"C:\evil"),
            ("WEBVIEW2_USER_DATA_FOLDER", r"C:\x"),
            ("PATH", "x"),
        ]);
        let mut gone = strip_webview2_env(&mut e);
        gone.sort();
        assert_eq!(
            gone,
            [
                "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
                "WEBVIEW2_USER_DATA_FOLDER",
                "webview2_browser_executable_folder"
            ]
        );
        assert_eq!(e.keys().collect::<Vec<_>>(), ["PATH"]);
    }

    // --- beyond the plan ----------------------------------------------------------------------

    #[test]
    fn the_key_may_be_upper_case_hex_but_must_be_exactly_64_digits() {
        let ok = |k: &str| config_from(&args(), Some("t".into()), Some(k.into())).is_ok();
        assert!(ok(&"AB".repeat(32)) && ok(&"ab".repeat(32)));
        assert!(!ok(&"11".repeat(33)) && !ok(&format!(" {}", "11".repeat(32))));
        assert!(!ok(&"1".repeat(63)) && !ok(&format!("{}+1", "11".repeat(31))));
    }

    #[test]
    fn the_debug_form_never_shows_the_token_or_the_key() {
        let cfg = config_from(&args(), Some("tok_SECRET".into()), Some("ab".repeat(32))).unwrap();
        let shown = format!("{cfg:?}");
        assert!(
            !shown.contains("tok_SECRET") && !shown.contains("171, 171"),
            "{shown}"
        );
        assert!(!shown.contains(&"ab".repeat(4)), "{shown}");
        assert!(shown.contains("http://127.0.0.1:8700"));
    }

    #[test]
    fn the_print_settings_are_kept() {
        let a = AgentArgs {
            dialog: Dialog::Print,
            url_file: Some(r"C:\t\agent.url".into()),
            unreachable_exit_sec: 2.5,
            ..args()
        };
        let cfg = config_from(&a, Some("t".into()), Some("11".repeat(32))).unwrap();
        assert_eq!(
            (
                cfg.dialog,
                cfg.url_file,
                cfg.unreachable_exit_sec,
                cfg.token
            ),
            (
                Dialog::Print,
                Some(r"C:\t\agent.url".into()),
                2.5,
                "t".to_string()
            )
        );
    }

    #[test]
    fn the_process_environment_gives_up_its_secrets() {
        // A name no other test or tool uses, so changing this process's environment is harmless.
        let name = "MCPMON_TEST_PROCESS_ENV_TAKE_7F3A";
        // SAFETY: Windows `SetEnvironmentVariableW` under std's environment lock (see ProcessEnv).
        unsafe { std::env::set_var(name, "v") };
        let mut env = ProcessEnv;
        assert!(env.names().iter().any(|n| n.eq_ignore_ascii_case(name)));
        assert_eq!(env.take(name).as_deref(), Some("v"));
        assert!(std::env::var_os(name).is_none());
        assert_eq!(env.take(name), None);
    }
}
