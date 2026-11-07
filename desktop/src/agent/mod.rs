//! `agent` mode: the per-session agent the service starts in every RDP session (it replaces the
//! Python `agent/mcp_agent`, same `/api/agent/*` contract, numbers and exit codes; Appendix B).
//! Task 9: settings, the HMAC-proving client, the runner and the `--dialog print` window.

pub mod client;
pub mod config;
pub mod runner;
#[cfg(test)]
pub mod testkit;
pub mod window;

use client::{ServerClient, UreqTransport};
use config::AgentConfig;
use runner::{AgentRunner, log_stderr};
use std::sync::Arc;

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

/// `agent --dialog print`: the runner with a [`window::PrintWindow`] on `--url-file`; returns the
/// exit code (0, 3, 4, 5; 1 when the session cannot be told).
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
    AgentRunner::new(
        cfg,
        client,
        Box::new(window::PrintWindow::new(url_file)),
        session_id,
        std::process::id(),
    )
    .with_log(log)
    .run()
}
