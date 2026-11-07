// desktop/tests/agent_webview.rs — a real WebView2 window on this desktop:
//   cargo test --locked --test agent_webview -- --ignored
mod common;
use common::{Scratch, agent_server::AgentServer, exe};
use serde_json::json;
use std::time::{Duration, Instant};
use windows::Win32::Foundation::{HWND, LPARAM, WPARAM};
use windows::Win32::UI::WindowsAndMessaging::*;
use windows::core::BOOL;

const PAGE: &str = "<!doctype html><title>notice</title><button>확인</button>";

fn windows_of(pid: u32) -> Vec<(HWND, String)> {
    unsafe extern "system" fn each(hwnd: HWND, l: LPARAM) -> BOOL {
        let out = unsafe { &mut *(l.0 as *mut (u32, Vec<(HWND, String)>)) };
        let mut p = 0u32;
        unsafe { GetWindowThreadProcessId(hwnd, Some(&mut p)) };
        if p == out.0 && unsafe { IsWindowVisible(hwnd) }.as_bool() {
            let mut buf = [0u16; 256];
            let n = unsafe { GetWindowTextW(hwnd, &mut buf) } as usize;
            out.1.push((hwnd, String::from_utf16_lossy(&buf[..n])));
        }
        true.into()
    }
    let mut acc: (u32, Vec<(HWND, String)>) = (pid, Vec::new());
    unsafe { EnumWindows(Some(each), LPARAM(&mut acc as *mut _ as isize)).ok() };
    acc.1
}

fn wait_for<T>(secs: u64, mut f: impl FnMut() -> Option<T>) -> T {
    let end = Instant::now() + Duration::from_secs(secs);
    loop {
        if let Some(v) = f() {
            return v;
        }
        assert!(Instant::now() < end, "timed out");
        std::thread::sleep(Duration::from_millis(100));
    }
}

fn notice_window(pid: u32) -> Option<HWND> {
    windows_of(pid)
        .into_iter()
        .find(|(_, t)| t == "MCP Monitor 고지")
        .map(|(h, _)| h)
}

/// The agent process; if the test fails, its exit status, standard error and the requests the
/// server saw are printed, and it is killed.
struct Agent<'a> {
    child: std::process::Child,
    stderr: std::path::PathBuf,
    srv: &'a AgentServer,
}

impl Agent<'_> {
    fn id(&self) -> u32 {
        self.child.id()
    }
}

impl Drop for Agent<'_> {
    fn drop(&mut self) {
        if std::thread::panicking() {
            eprintln!("agent status: {:?}", self.child.try_wait());
            eprintln!(
                "agent stderr:\n{}",
                std::fs::read_to_string(&self.stderr).unwrap_or_default()
            );
            let paths: Vec<String> = self.srv.requests().into_iter().map(|r| r.path).collect();
            eprintln!("requests: {paths:?}");
            describe_windows(self.child.id());
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// The agent with its own `%LOCALAPPDATA%` (F23: the notice profile goes to the scratch folder).
fn spawn_agent<'a>(srv: &'a AgentServer, scratch: &Scratch) -> Agent<'a> {
    let stderr = scratch.join("agent-stderr.txt");
    let child = exe()
        .args(["agent", "--server", &srv.url()])
        .env("MCPMON_AGENT_TOKEN", "tok")
        .env("MCPMON_AGENT_SERVER_KEY", "11".repeat(32))
        .env("LOCALAPPDATA", scratch.path())
        .env("RUST_BACKTRACE", "1")
        .stderr(std::fs::File::create(&stderr).unwrap())
        .spawn()
        .unwrap();
    Agent { child, stderr, srv }
}

/// WebView2 processes can hold the profile for a moment after the agent exits.
fn remove_profile(scratch: &Scratch) {
    let profile = scratch.join("mcp-monitor");
    wait_for(15, || {
        (!profile.exists() || std::fs::remove_dir_all(&profile).is_ok()).then_some(())
    });
}

#[test]
#[ignore = "opens a real WebView2 window on this desktop"]
fn webview_notice_is_topmost_ignores_wm_close_and_closes_on_command() {
    let scratch = Scratch::new();
    let srv = AgentServer::start(Some([0x11; 32]));
    srv.serve_page("/notice", PAGE);
    let notice = format!("{}/notice#d=7&t=tok_ABCDEFGHIJKLmnop", srv.url());
    srv.queue(json!({"type": "show_notice", "display_id": 7, "attempt": 1, "url": notice}));
    let mut agent = spawn_agent(&srv, &scratch);
    let hwnd = wait_for(30, || notice_window(agent.id()));
    let ex = unsafe { GetWindowLongPtrW(hwnd, GWL_EXSTYLE) } as u32;
    assert!(ex & WS_EX_TOPMOST.0 != 0, "not top-most");
    let state = unsafe { GetMenuState(GetSystemMenu(hwnd, false), SC_CLOSE, MF_BYCOMMAND) };
    assert!(
        state & (MF_GRAYED.0 | MF_DISABLED.0) != 0,
        "close is enabled"
    );
    unsafe { PostMessageW(Some(hwnd), WM_CLOSE, WPARAM(0), LPARAM(0)).unwrap() };
    std::thread::sleep(Duration::from_secs(1));
    assert!(
        unsafe { IsWindow(Some(hwnd)) }.as_bool(),
        "WM_CLOSE closed the notice"
    );
    // the profile is the notice profile under this user's %LOCALAPPDATA%
    assert!(scratch.join(r"mcp-monitor\notice-webview").is_dir());
    srv.queue(json!({"type": "close_notice", "display_id": 7}));
    wait_for(5, || {
        (!unsafe { IsWindow(Some(hwnd)) }.as_bool()).then_some(())
    });
    srv.queue(json!({"type": "exit"}));
    assert_eq!(agent.child.wait().unwrap().code(), Some(0));
    assert!(
        !srv.requests()
            .iter()
            .any(|r| r.path == "/api/agent/notice/7/closed")
    );
    remove_profile(&scratch);
}

/// Diagnostics: the visible top-level windows of `pid` with their classes.
fn describe_windows(pid: u32) {
    for (hwnd, title) in windows_of(pid) {
        let mut class = [0u16; 256];
        let n = unsafe { GetClassNameW(hwnd, &mut class) } as usize;
        eprintln!(
            "window {hwnd:?} class {:?} title {title:?}",
            String::from_utf16_lossy(&class[..n])
        );
    }
}
