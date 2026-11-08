// desktop/tests/app_window.rs — real WebView2 windows of `mcp-monitor.exe app` on this desktop:
//   cargo test --locked --features dev --test app_window -- --ignored --test-threads=1
// One at a time: the app is a single instance per session.
#![cfg(feature = "dev")]
mod common;
use common::{Scratch, agent_server::AgentServer, exe};
use std::time::{Duration, Instant};
use windows::Win32::Foundation::{HWND, LPARAM, WPARAM};
use windows::Win32::UI::WindowsAndMessaging::*;
use windows::core::BOOL;

#[test]
#[ignore = "opens a real WebView2 window on this desktop"]
fn the_app_window_opens_the_status_board_of_its_server() {
    let srv = AgentServer::start(None);
    srv.serve_page("/api/channel", r#"{"channel":"local"}"#);
    srv.serve_page("/", BOARD_PAGE);
    let cdp = std::net::TcpListener::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port();
    let s = Scratch::new();
    let mut child = App::spawn(&srv, &s, cdp, &[]);
    let want = home_of(&srv);
    let end = Instant::now() + Duration::from_secs(20);
    let found = loop {
        let pages = ureq::get(&format!("http://127.0.0.1:{cdp}/json/list"))
            .call()
            .ok()
            .and_then(|mut r| r.body_mut().read_to_string().ok());
        if pages.as_deref().is_some_and(|p| shows(p, &want)) {
            break true;
        }
        if Instant::now() > end {
            break false;
        }
        std::thread::sleep(Duration::from_millis(250));
    };
    child.stop();
    assert!(found, "no WebView2 page at {want}");
    // the window's profile is this user's %LOCALAPPDATA%\mcp-monitor\webview
    assert!(s.join(r"mcp-monitor\webview").is_dir());
    remove_profile(&s);
}

#[test]
#[ignore = "opens a real WebView2 window on this desktop"]
fn closing_hides_the_window_and_a_second_start_brings_it_back() {
    let srv = AgentServer::start(None);
    srv.serve_page("/api/channel", r#"{"channel":"local"}"#);
    srv.serve_page("/", BOARD_PAGE);
    let cdp = free_port();
    let s = Scratch::new();
    let mut app = App::spawn(&srv, &s, cdp, &["--background"]);
    let want = home_of(&srv);
    wait_for(30, || cdp_pages(cdp).filter(|p| shows(p, &want)));
    let hwnd = wait_for(10, || main_window(app.id()));
    assert!(!visible(hwnd), "--background shows no window");

    // a second start hands over to the first and ends; the first shows its window
    second_start(&srv);
    wait_for(10, || visible(hwnd).then_some(()));
    let style = unsafe { GetWindowLongPtrW(hwnd, GWL_STYLE) } as u32;
    assert!(style & WS_THICKFRAME.0 != 0, "the window can be resized");

    // closing only hides it: the app (and its tray) stays
    unsafe { PostMessageW(Some(hwnd), WM_CLOSE, WPARAM(0), LPARAM(0)).unwrap() };
    wait_for(10, || (!visible(hwnd)).then_some(()));
    std::thread::sleep(Duration::from_millis(500));
    assert!(unsafe { IsWindow(Some(hwnd)) }.as_bool(), "closed for good");
    assert!(app.child.try_wait().unwrap().is_none(), "the app ended");
    assert_eq!(
        windows_titled(app.id()).len(),
        1,
        "one main window, no other"
    );

    second_start(&srv);
    wait_for(10, || visible(hwnd).then_some(()));
    app.stop();
    remove_profile(&s);
}

#[test]
#[ignore = "opens a real WebView2 window on this desktop; waits 30 s"]
fn a_server_that_does_not_answer_shows_the_stopped_text_then_the_status_board() {
    let srv = AgentServer::start(None);
    srv.serve_page("/", BOARD_PAGE);
    let cdp = free_port();
    let s = Scratch::new();
    let mut app = App::spawn(&srv, &s, cdp, &[]);
    // /api/channel answers 404: after 30 s the connecting page says the service is stopped
    let start = Instant::now();
    wait_for(45, || {
        cdp_pages(cdp).filter(|p| p.contains("tauri.localhost/index.html#stopped"))
    });
    assert!(
        start.elapsed() >= Duration::from_secs(25),
        "#stopped after {:?}",
        start.elapsed()
    );
    let want = home_of(&srv);
    assert!(!shows(&cdp_pages(cdp).unwrap_or_default(), &want));
    // the service comes back: the next try (every 5 s) opens the status board
    srv.serve_page("/api/channel", r#"{"channel":"local"}"#);
    wait_for(15, || cdp_pages(cdp).filter(|p| shows(p, &want)));
    app.stop();
    remove_profile(&s);
}

/// What the fake server answers at `/`: the window's home is the status board.
const BOARD_PAGE: &str = "<!doctype html><title>board</title><p>board</p>";

/// The status board of `srv`, exactly as the window's address shows it (`http://127.0.0.1:<port>/`).
fn home_of(srv: &AgentServer) -> String {
    format!("{}/", srv.url().trim_end_matches('/'))
}

/// True when one of the DevTools `pages` shows exactly `url` (not a page under it, like `/admin`).
fn shows(pages: &str, url: &str) -> bool {
    serde_json::from_str::<Vec<serde_json::Value>>(pages)
        .unwrap_or_default()
        .iter()
        .any(|p| p["url"].as_str() == Some(url))
}

fn free_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port()
}

/// The WebView2 pages (DevTools protocol list) of the app started with `--remote-debugging-port`.
fn cdp_pages(cdp: u16) -> Option<String> {
    ureq::get(&format!("http://127.0.0.1:{cdp}/json/list"))
        .call()
        .ok()
        .and_then(|mut r| r.body_mut().read_to_string().ok())
}

fn wait_for<T>(secs: u64, mut f: impl FnMut() -> Option<T>) -> T {
    let end = Instant::now() + Duration::from_secs(secs);
    loop {
        if let Some(v) = f() {
            return v;
        }
        assert!(Instant::now() < end, "timed out after {secs} s");
        std::thread::sleep(Duration::from_millis(200));
    }
}

/// `mcp-monitor.exe app --server-url <srv>` again: it must hand over and exit 0 at once.
fn second_start(srv: &AgentServer) {
    let mut second = exe()
        .args(["app", "--server-url", &srv.url()])
        .spawn()
        .unwrap();
    let status = wait_for(15, || second.try_wait().unwrap());
    assert_eq!(status.code(), Some(0), "the second start");
}

/// Top-level windows of `pid` titled "MCP Monitor" (visible or not).
fn windows_titled(pid: u32) -> Vec<HWND> {
    unsafe extern "system" fn each(hwnd: HWND, l: LPARAM) -> BOOL {
        let out = unsafe { &mut *(l.0 as *mut (u32, Vec<HWND>)) };
        let mut p = 0u32;
        unsafe { GetWindowThreadProcessId(hwnd, Some(&mut p)) };
        if p == out.0 {
            let mut buf = [0u16; 256];
            let n = unsafe { GetWindowTextW(hwnd, &mut buf) } as usize;
            if String::from_utf16_lossy(&buf[..n]) == "MCP Monitor" {
                out.1.push(hwnd);
            }
        }
        true.into()
    }
    let mut acc: (u32, Vec<HWND>) = (pid, Vec::new());
    unsafe { EnumWindows(Some(each), LPARAM(&mut acc as *mut _ as isize)).ok() };
    acc.1
}

fn main_window(pid: u32) -> Option<HWND> {
    windows_titled(pid).into_iter().next()
}

fn visible(hwnd: HWND) -> bool {
    unsafe { IsWindowVisible(hwnd) }.as_bool()
}

/// The app with its own `%LOCALAPPDATA%` and DevTools port; killed (and its standard error
/// printed when the test fails) on drop.
struct App {
    child: std::process::Child,
    stderr: std::path::PathBuf,
    scratch: std::path::PathBuf,
    cdp: u16,
}

impl App {
    fn spawn(srv: &AgentServer, s: &Scratch, cdp: u16, extra: &[&str]) -> App {
        let stderr = s.join("app-stderr.txt");
        let child = exe()
            .args(["app", "--server-url", &srv.url()])
            .args(extra)
            .env(
                "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
                format!("--remote-debugging-port={cdp}"),
            )
            .env("LOCALAPPDATA", s.path())
            .stderr(std::fs::File::create(&stderr).unwrap())
            .spawn()
            .unwrap();
        App {
            child,
            stderr,
            scratch: s.path().to_path_buf(),
            cdp,
        }
    }

    fn id(&self) -> u32 {
        self.child.id()
    }

    fn stop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for App {
    fn drop(&mut self) {
        if std::thread::panicking() {
            eprintln!("app status: {:?}", self.child.try_wait());
            eprintln!(
                "app stderr:\n{}",
                std::fs::read_to_string(&self.stderr).unwrap_or_default()
            );
            eprintln!("app windows: {:?}", windows_titled(self.child.id()));
            let listening = std::net::TcpStream::connect(("127.0.0.1", self.cdp)).is_ok();
            eprintln!("DevTools port {} listening: {listening}", self.cdp);
            eprintln!("DevTools pages: {:?}", cdp_pages(self.cdp));
            describe_webview_processes(&self.scratch);
        }
        self.stop();
    }
}

/// WebView2 processes can hold the profile for a moment after the app is gone.
fn remove_profile(s: &Scratch) {
    let profile = s.join("mcp-monitor");
    wait_for(15, || {
        (!profile.exists() || std::fs::remove_dir_all(&profile).is_ok()).then_some(())
    });
}

/// Diagnostics: the WebView2 processes that use this test's profile, with their command lines.
fn describe_webview_processes(scratch: &std::path::Path) {
    let filter = scratch.display().to_string().replace('\'', "''");
    let script = format!(
        "Get-CimInstance Win32_Process -Filter \"Name='msedgewebview2.exe'\" | Where-Object {{ $_.CommandLine -like '*{filter}*' }} | ForEach-Object {{ \"$($_.ProcessId) $($_.ParentProcessId) $($_.CommandLine)\" }}"
    );
    let out = std::process::Command::new("powershell.exe")
        .args(["-NoProfile", "-NonInteractive", "-Command", &script])
        .output();
    match out {
        Ok(o) => eprintln!(
            "WebView2 processes:\n{}{}",
            String::from_utf8_lossy(&o.stdout),
            String::from_utf8_lossy(&o.stderr)
        ),
        Err(e) => eprintln!("WebView2 processes: {e}"),
    }
}
