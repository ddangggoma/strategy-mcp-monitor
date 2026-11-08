mod common;
use common::{Scratch, agent_server::AgentServer, exe};
use serde_json::json;
use std::time::Instant;

fn agent(
    srv: &AgentServer,
    url_file: &std::path::Path,
    key: Option<&str>,
) -> std::process::Command {
    let mut c = exe();
    c.args([
        "agent",
        "--server",
        &srv.url(),
        "--dialog",
        "print",
        "--url-file",
    ])
    .arg(url_file)
    .env("MCPMON_AGENT_TOKEN", "tok");
    if let Some(k) = key {
        c.env("MCPMON_AGENT_SERVER_KEY", k);
    }
    c
}

#[test]
fn the_print_agent_shows_closes_and_exits_ignoring_proxy_settings() {
    let srv = AgentServer::start(Some([0x11; 32]));
    let s = Scratch::new();
    let url_file = s.join("agent.url");
    let notice = format!("{}/notice#d=7&t=tok_ABCDEFGHIJKLmnop", srv.url());
    srv.queue(json!({"type": "show_notice", "display_id": 7, "attempt": 1, "url": notice}));
    srv.queue(json!({"type": "close_notice", "display_id": 7}));
    srv.queue(json!({"type": "exit"}));
    let child = agent(&srv, &url_file, Some(&"11".repeat(32)))
        .env("HTTP_PROXY", "http://127.0.0.1:9")
        .env("http_proxy", "http://127.0.0.1:9")
        .env("ALL_PROXY", "http://127.0.0.1:9")
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    let pid = child.id();
    let out = child.wait_with_output().unwrap();
    assert_eq!(
        out.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let lines: Vec<String> = std::fs::read_to_string(&url_file)
        .unwrap()
        .lines()
        .map(String::from)
        .collect();
    assert_eq!(lines, [format!("OPEN 7 {notice}"), "CLOSE 7".to_string()]);
    let hello = srv
        .requests()
        .into_iter()
        .find(|r| r.path == "/api/agent/hello")
        .unwrap();
    assert_eq!(
        (hello.body["pid"].as_u64(), hello.body["version"].as_str()),
        (Some(pid as u64), Some("1.0.0"))
    );
    // Beyond the plan: every request carried the token, and nothing was printed with it.
    assert!(srv.requests().iter().all(|r| r.token == "tok"));
    assert!(!String::from_utf8_lossy(&out.stderr).contains("tok_ABCDEFGHIJKLmnop"));
}

#[test]
fn a_rogue_server_is_left_within_seconds_with_exit_5() {
    let srv = AgentServer::start(Some([0x33; 32]));
    let s = Scratch::new();
    let url_file = s.join("agent.url");
    srv.queue(json!({"type": "show_notice", "display_id": 7, "attempt": 1, "url": format!("{}/notice#d=7&t=x", srv.url())}));
    let started = Instant::now();
    let out = agent(&srv, &url_file, Some(&"11".repeat(32)))
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(5));
    assert!(started.elapsed().as_secs() < 15 && !url_file.exists());
    assert!(String::from_utf8_lossy(&out.stderr).contains("does not prove the server key"));
}

#[test]
fn an_agent_without_the_server_key_exits_2() {
    let srv = AgentServer::start(Some([0x11; 32]));
    let s = Scratch::new();
    let out = agent(&srv, &s.join("agent.url"), None).output().unwrap();
    assert_eq!(out.status.code(), Some(2));
    assert!(srv.requests().is_empty());
    // Beyond the plan: the argument error is reported like every other one.
    assert_eq!(
        String::from_utf8(out.stderr).unwrap().trim_end(),
        "오류: MCPMON_AGENT_SERVER_KEY는 32바이트 hex여야 합니다"
    );
}
