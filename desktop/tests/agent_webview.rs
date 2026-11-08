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

/// The notice page of the first test: once loaded (it fetches `/ran`, so the script is known to
/// have run), it tries to open a window and to navigate away, and 1.5 s later fetches
/// `/still-here`, which only a page that was not replaced can do.
const SCRIPTED_PAGE: &str = "<!doctype html><title>notice</title><button>확인</button>\
<script>fetch('/ran').finally(() => { setTimeout(() => fetch('/still-here'), 1500); \
window.open('/popup'); location.href = '/elsewhere'; });</script>";

#[test]
#[ignore = "opens a real WebView2 window on this desktop"]
fn webview_notice_is_topmost_ignores_wm_close_and_closes_on_command() {
    let scratch = Scratch::new();
    let srv = AgentServer::start(Some([0x11; 32]));
    srv.serve_page("/notice", SCRIPTED_PAGE);
    let notice = format!("{}/notice#d=7&t=tok_ABCDEFGHIJKLmnop", srv.url());
    srv.queue(json!({"type": "show_notice", "display_id": 7, "attempt": 1, "url": notice}));
    let mut agent = spawn_agent(&srv, &scratch);
    let hwnd = wait_for(30, || notice_window(agent.id()));
    let ex = unsafe { GetWindowLongPtrW(hwnd, GWL_EXSTYLE) } as u32;
    assert!(ex & WS_EX_TOPMOST.0 != 0, "not top-most");
    // The window can be found before the agent greys its close item (that runs on the main
    // thread right after creation, and again on every top-most tick), so give it a few ticks.
    let close_greyed = || {
        let state = unsafe { GetMenuState(GetSystemMenu(hwnd, false), SC_CLOSE, MF_BYCOMMAND) };
        state & (MF_GRAYED.0 | MF_DISABLED.0) != 0
    };
    let until = Instant::now() + Duration::from_secs(5);
    while !close_greyed() && Instant::now() < until {
        std::thread::sleep(Duration::from_millis(100));
    }
    assert!(close_greyed(), "close is enabled");
    // Review item 12: the window the builder made, not the spec constant. A title bar (it can be
    // moved), no minimise or maximise button, no sizing border; 640×600 logical px inside.
    let style = unsafe { GetWindowLongPtrW(hwnd, GWL_STYLE) } as u32;
    assert_eq!(
        style & WS_CAPTION.0,
        WS_CAPTION.0,
        "no title bar: {style:#x}"
    );
    assert_eq!(
        style & (WS_MINIMIZEBOX.0 | WS_MAXIMIZEBOX.0 | WS_THICKFRAME.0),
        0,
        "minimise, maximise or resize is possible: {style:#x}"
    );
    // This test exe has no DPI-aware manifest: Windows gives it the window's size in logical px.
    let mut client = windows::Win32::Foundation::RECT::default();
    unsafe { GetClientRect(hwnd, &mut client).unwrap() };
    let (w, h) = (client.right - client.left, client.bottom - client.top);
    assert!(
        (w - 640).abs() <= 2 && (h - 600).abs() <= 2,
        "client area {w}×{h}"
    );
    // The page ran its script and is still the one shown after trying to leave (navigation
    // refused); its window.open never reached the server, and the agent shows no other window.
    // (WebView2 may already have sent the GET for a navigation it then cancels: the refused page
    // is never shown, which is what the navigation rule promises.)
    let has = |path: &str| srv.requests().iter().any(|r| r.path == path);
    wait_for(15, || has("/ran").then_some(()));
    wait_for(15, || has("/still-here").then_some(()));
    assert!(!has("/popup"), "window.open reached the server");
    {
        use std::io::Write;
        let _ = writeln!(
            std::io::stderr(),
            "notice page: refused navigation to /elsewhere {} the server",
            if has("/elsewhere") {
                "reached"
            } else {
                "did not reach"
            }
        );
    }
    let titled: Vec<String> = windows_of(agent.id())
        .into_iter()
        .map(|(_, t)| t)
        .filter(|t| !t.is_empty())
        .collect();
    assert_eq!(titled, ["MCP Monitor 고지"]);
    assert!(unsafe { IsWindow(Some(hwnd)) }.as_bool());
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

/// (pid, parent pid, image name) of every running process.
fn process_table() -> Vec<(u32, u32, String)> {
    use windows::Win32::System::Diagnostics::ToolHelp::*;
    let snap = unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) }.unwrap();
    let mut e = PROCESSENTRY32W {
        dwSize: size_of::<PROCESSENTRY32W>() as u32,
        ..Default::default()
    };
    let mut out = Vec::new();
    let mut more = unsafe { Process32FirstW(snap, &mut e) }.is_ok();
    while more {
        let n = e.szExeFile.iter().position(|&c| c == 0).unwrap_or(260);
        out.push((
            e.th32ProcessID,
            e.th32ParentProcessID,
            String::from_utf16_lossy(&e.szExeFile[..n]),
        ));
        more = unsafe { Process32NextW(snap, &mut e) }.is_ok();
    }
    let _ = unsafe { windows::Win32::Foundation::CloseHandle(snap) };
    out
}

/// The WebView2 browser processes the agent `pid` started (`msedgewebview2.exe` children).
fn browsers_of(pid: u32) -> Vec<u32> {
    process_table()
        .into_iter()
        .filter(|(_, parent, name)| {
            *parent == pid && name.eq_ignore_ascii_case("msedgewebview2.exe")
        })
        .map(|(p, ..)| p)
        .collect()
}

/// `root` and every process below it (renderers, GPU, utility), the root first.
fn tree_of(root: u32) -> Vec<u32> {
    let table = process_table();
    let mut tree = vec![root];
    let mut i = 0;
    while i < tree.len() {
        let parent = tree[i];
        tree.extend(
            table
                .iter()
                .filter(|(p, pp, _)| *pp == parent && !tree.contains(p))
                .map(|(p, ..)| *p)
                .collect::<Vec<_>>(),
        );
        i += 1;
    }
    tree
}

/// Ends `pid` and waits up to 10 s for it to be gone; what happened, for the log.
fn kill(pid: u32) -> String {
    use windows::Win32::System::Threading::*;
    let h = match unsafe { OpenProcess(PROCESS_TERMINATE | PROCESS_SYNCHRONIZE, false, pid) } {
        Ok(h) => h,
        Err(e) => return format!("{pid}: not opened ({e})"),
    };
    let ended = unsafe { TerminateProcess(h, 1) };
    let waited = unsafe { WaitForSingleObject(h, 10_000) };
    let _ = unsafe { windows::Win32::Foundation::CloseHandle(h) };
    format!("{pid}: terminate {ended:?}, wait {waited:?}")
}

/// Review I3 / Review Focus 6: the user ends the notice's WebView2 browser in Task Manager. The
/// agent reports the notice closed (once), closes the dead window, and the server's next
/// `show_notice` brings a fresh, working window. The agent's log says which signal saw it.
#[test]
#[ignore = "opens a real WebView2 window on this desktop"]
fn a_killed_webview2_browser_is_reported_closed_and_a_fresh_window_replaces_it() {
    let scratch = Scratch::new();
    let srv = AgentServer::start(Some([0x11; 32]));
    srv.serve_page("/notice", PAGE);
    let show = |d: i64| {
        json!({"type": "show_notice", "display_id": d, "attempt": 1,
               "url": format!("{}/notice#d={d}&t=tok_ABCDEFGHIJKLmnop", srv.url())})
    };
    srv.queue(show(7));
    let mut agent = spawn_agent(&srv, &scratch);
    let first = wait_for(30, || notice_window(agent.id()));
    // The browser process WebView2 reports (BrowserProcessId), as the agent logs it: it is not
    // always a direct child of the agent (on the runner an msedgewebview2.exe child of the agent
    // had no children, and ending it changed nothing).
    let browsers = wait_for(30, || {
        let log = std::fs::read_to_string(&agent.stderr).unwrap_or_default();
        log.lines()
            .find_map(|l| l.split("watching the WebView2 browser process ").nth(1))
            .and_then(|pid| pid.trim().parse::<u32>().ok())
            .map(|pid| vec![pid])
    });
    {
        use std::io::Write;
        let _ = writeln!(
            std::io::stderr(),
            "msedgewebview2.exe children of the agent: {:?}",
            browsers_of(agent.id())
        );
    }
    let mut killed = Vec::new();
    for browser in &browsers {
        for pid in tree_of(*browser) {
            killed.push(kill(pid));
        }
    }
    {
        use std::io::Write;
        let _ = writeln!(
            std::io::stderr(),
            "browser processes {browsers:?} ended: {killed:?}"
        );
    }
    wait_for(20, || {
        srv.requests()
            .iter()
            .any(|r| r.path == "/api/agent/notice/7/closed")
            .then_some(())
    });
    wait_for(10, || {
        (!unsafe { IsWindow(Some(first)) }.as_bool()).then_some(())
    });
    let pages = || {
        srv.requests()
            .iter()
            .filter(|r| r.path == "/notice")
            .count()
    };
    let before = pages();
    // The server shows it again (here: the next command).
    srv.queue(show(8));
    let second = wait_for(30, || notice_window(agent.id()));
    assert!(unsafe { IsWindow(Some(second)) }.as_bool());
    wait_for(30, || (pages() > before).then_some(()));
    // The fresh window has a browser process of its own (a second "watching" line).
    wait_for(30, || {
        let log = std::fs::read_to_string(&agent.stderr).unwrap_or_default();
        (log.matches("watching the WebView2 browser process").count() >= 2).then_some(())
    });
    std::thread::sleep(Duration::from_secs(3));
    assert!(
        unsafe { IsWindow(Some(second)) }.as_bool(),
        "the fresh window went away"
    );
    let closed: Vec<String> = srv
        .requests()
        .into_iter()
        .map(|r| r.path)
        .filter(|p| p.ends_with("/closed"))
        .collect();
    assert_eq!(closed, ["/api/agent/notice/7/closed"]);
    srv.queue(json!({"type": "close_notice", "display_id": 8}));
    srv.queue(json!({"type": "exit"}));
    assert_eq!(agent.child.wait().unwrap().code(), Some(0));
    let log = std::fs::read_to_string(&agent.stderr).unwrap_or_default();
    {
        use std::io::Write;
        let _ = writeln!(std::io::stderr(), "agent log:\n{log}");
    }
    assert!(
        log.contains("WebView2 process failed (kind 0)")
            || log.contains("WebView2 browser process exited")
            || log.contains("the WebView2 browser process is gone"),
        "{log}"
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
