//! `agent` mode: the per-session agent the service starts in every RDP session (it replaces the
//! Python `agent/mcp_agent`, same `/api/agent/*` contract, numbers and exit codes; Appendix B).
//! Task 9: settings, the HMAC-proving client, the runner and the `--dialog print` window.
//! Task 10: window events and idle (hooks, coalescing, batched sending, title redaction).

pub mod activity;
pub mod client;
pub mod coalesce;
pub mod config;
pub mod hooks;
pub mod idle;
pub mod pump;
pub mod redact;
pub mod runner;
pub mod sender;
#[cfg(test)]
pub mod testkit;
pub mod time;
pub mod window;

use activity::WindowActivity;
use client::{ServerClient, UreqTransport};
use config::AgentConfig;
use runner::{AgentRunner, log_stderr};
use std::sync::{Arc, Mutex};

/// The Remote Desktop session this process runs in.
pub fn current_session_id() -> Result<u32, String> {
    use windows::Win32::System::RemoteDesktop::ProcessIdToSessionId;
    use windows::Win32::System::Threading::GetCurrentProcessId;
    let mut session = 0u32;
    // SAFETY: plain calls; the out pointer is valid for the call.
    unsafe { ProcessIdToSessionId(GetCurrentProcessId(), &mut session) }
        .map_err(|e| e.to_string())?;
    Ok(session)
}

/// Runs `runner` with `activity` started by the server's HELLO, and stopped (hooks, pump, one last
/// flush) when the runner ends; returns the runner's exit code.
pub fn run_with_activity(runner: AgentRunner, activity: WindowActivity) -> i32 {
    let activity = Arc::new(Mutex::new(activity));
    let on_hello = activity.clone();
    let code = runner
        .on_hello(Box::new(move |hello| {
            on_hello
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .on_hello(hello)
        }))
        .run();
    activity.lock().unwrap_or_else(|e| e.into_inner()).stop();
    code
}

/// `agent --dialog print`: the runner with a [`window::PrintWindow`] on `--url-file` and the
/// window activity; returns the exit code (0, 3, 4, 5; 1 when the session cannot be told).
pub fn run_print(cfg: &AgentConfig) -> i32 {
    let log = log_stderr();
    let Some(url_file) = cfg.url_file.clone() else {
        log("--dialog print needs --url-file");
        return 2;
    };
    let session_id = match current_session_id() {
        Ok(id) => id,
        Err(e) => {
            log(&format!("cannot tell this process's session: {e}"));
            return 1;
        }
    };
    let client = Arc::new(ServerClient::new(
        cfg.server.clone(),
        cfg.token.clone(),
        cfg.server_key,
        Box::new(UreqTransport::new()),
    ));
    let runner = AgentRunner::new(
        cfg,
        client.clone(),
        Box::new(window::PrintWindow::new(url_file)),
        session_id,
        std::process::id(),
    )
    .with_log(log.clone());
    run_with_activity(runner, WindowActivity::new(client).with_log(log))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::testkit::*;
    use crate::cli::Dialog;
    use serde_json::json;

    fn cfg() -> AgentConfig {
        AgentConfig {
            server: BASE.into(),
            token: "tok".into(),
            server_key: KEY,
            dialog: Dialog::Print,
            url_file: None,
            unreachable_exit_sec: 120.0,
        }
    }

    #[test]
    fn the_runner_starts_window_events_on_hello_and_they_stop_with_it() {
        let fake = FakeServer::new();
        // the agent is told to exit once its first event batch arrived
        fake.on_answer("/api/agent/events", |st| {
            st.commands.push_back(json!({"type": "exit"}))
        });
        let c = client(&fake);
        let dir = tempfile::tempdir().unwrap();
        let runner = AgentRunner::new(
            &cfg(),
            c.clone(),
            Box::new(window::PrintWindow::new(dir.path().join("urls.txt"))),
            2,
            1,
        )
        .with_idle(Arc::new(|| Some(0.0)));
        let activity = WindowActivity::new(c)
            .with_idle_source(Arc::new(|| Some(400.0)))
            .with_no_hooks();
        assert_eq!(run_with_activity(runner, activity), runner::EXIT_OK);
        let st = fake.state();
        let paths: Vec<&str> = st.requests.iter().map(|r| r.path.as_str()).collect();
        assert_eq!(paths.first(), Some(&"/api/agent/hello"));
        let events = st
            .requests
            .iter()
            .find(|r| r.path == "/api/agent/events")
            .and_then(|r| r.body.clone())
            .unwrap();
        assert_eq!(events["events"][0]["type"], "idle");
        assert_eq!(events["events"][0]["idle_sec"], 400);
    }

    #[test]
    fn no_window_events_when_the_server_turns_them_off() {
        let fake = FakeServer::new();
        fake.state().hello = json!({"heartbeat_sec": 5, "window_events": false});
        fake.state().commands.push_back(json!({"type": "exit"}));
        let c = client(&fake);
        let dir = tempfile::tempdir().unwrap();
        let runner = AgentRunner::new(
            &cfg(),
            c.clone(),
            Box::new(window::PrintWindow::new(dir.path().join("urls.txt"))),
            2,
            1,
        )
        .with_idle(Arc::new(|| Some(0.0)));
        let activity = WindowActivity::new(c)
            .with_idle_source(Arc::new(|| Some(400.0)))
            .with_hooks(Box::new(|_| panic!("no hooks when window events are off")));
        assert_eq!(run_with_activity(runner, activity), runner::EXIT_OK);
        assert!(
            !fake
                .state()
                .requests
                .iter()
                .any(|r| r.path == "/api/agent/events")
        );
    }
}
